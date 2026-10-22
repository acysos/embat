# Copyright 2025 Acysos S.L. (https://www.acysos.com)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools import DEFAULT_SERVER_DATE_FORMAT as DF
import datetime


EMBAT_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"


class OnlineBankStatementProviderEmbat(models.Model):
    _name = "online.bank.statement.provider"
    _inherit = "online.bank.statement.provider"

    embat_data_id = fields.Many2one(
        comodel_name="embat.data",
        string="Embat Data",
        help="Data related to Embat integration.",
    )
    embat_account_bank_id = fields.Char(
        string="Embat Bank ID",
        help="The ID of the bank to use for Embat integration.",
        readonly=True,
        compute="_embat_get_bank_id",
        store=True,
    )
    embat_date_type = fields.Selection(
        string="Date type for Embat Import",
        selection=[("valued_date", "Value Date"), ("operation_date", "Operation Date")],
        default="valued_date",
    )

    @api.model
    def _get_available_services(self):
        """Include the new service Embat in the online providers."""
        return super()._get_available_services() + [
            ("embat", "Embat"),
        ]

    @api.depends("embat_data_id", "embat_data_id.embat_company_id", "account_number")
    def _embat_get_bank_id(self):
        """Obtains the bank ID from the Embat API according to the name."""
        for provider in self:
            provider.embat_account_bank_id = False
            if provider.embat_data_id:
                endpoint = "banks/" + provider.embat_data_id.embat_company_id
                response, content = provider.embat_data_id._embat_request(endpoint, provider)
                if not content or "data" not in content:
                    message = _("Could not retrieve the list of banks from Embat: %s") % (response)
                    provider.embat_data_id._create_log("ERROR", "ERROR", message, provider)
                    continue
                message = _("List of banks retrieved from Embat successfully.")
                provider.embat_data_id._create_log("INFO", "INFO", message, provider)
                acc_number = provider.account_number.lower() if provider.account_number else False
                if acc_number:
                    found_bank_id = False
                    for bank in content["data"]:
                        for bankproduct in bank.get("bankProducts", []):
                            accountnumber = bankproduct.get("accountNumber")
                            accountnumber = accountnumber.lower() if accountnumber else ""
                            if accountnumber == acc_number:
                                found_bank_id = bankproduct["id"]
                                break
                        if found_bank_id:
                            break
                    provider.embat_account_bank_id = found_bank_id
                    if not found_bank_id:
                        message = _("The bank was not found in Embat.")
                        provider.embat_data_id._create_log("ERROR", "ERROR", message, provider)
                else:
                    message = _("No bank account in journal")
                    provider.embat_data_id._create_log("ERROR", "ERROR", message, provider)


    def _pull(self, date_since, date_until):
        """Override _pull for Embat providers to look back a configurable window
        (default 7 days) on scheduled pulls so transactions consolidated as BOOKED
        asynchronously (e.g. D+1, weekends, or past value dates) are not missed,
        and prefetch transactions once for the whole range.
        """
        embat_providers = self.filtered(lambda p: p.service == "embat")
        other_providers = self - embat_providers
        is_scheduled = self.env.context.get("scheduled")
        debug_data = []
        if other_providers:
            res = super(OnlineBankStatementProviderEmbat, other_providers)._pull(
                date_since, date_until
            )
            if res:
                debug_data += res
        if embat_providers:
            embat_date_since = date_since
            if is_scheduled:
                lookback_days = int(
                    self.env["ir.config_parameter"]
                    .sudo()
                    .get_param("embat.statement_lookback_days", 7)
                )
                lookback_date = fields.Datetime.now() - datetime.timedelta(
                    days=lookback_days
                )
                if not embat_date_since or embat_date_since > lookback_date:
                    embat_date_since = lookback_date
            for provider in embat_providers:
                old_last_successful_run = provider.last_successful_run
                statement_date_since = provider._get_statement_date_since(
                    embat_date_since
                )
                statement_date_until = date_until
                step = provider._get_statement_date_step()
                cur = statement_date_since
                while cur < date_until:
                    cur += step
                if cur > statement_date_until:
                    statement_date_until = cur
                pull_cache = {}
                provider_ctx = provider.with_context(
                    embat_pull_range=(statement_date_since, statement_date_until),
                    embat_pull_cache=pull_cache,
                )
                res = super(OnlineBankStatementProviderEmbat, provider_ctx)._pull(
                    embat_date_since, date_until
                )
                if is_scheduled and provider.id not in pull_cache:
                    provider.last_successful_run = old_last_successful_run
                if res:
                    debug_data += res
        return debug_data

    def _obtain_statement_data(self, date_since, date_until):
        """Generic online cron overrided for acting when the sync is for GoCardless."""
        self.ensure_one()
        if self.service == "embat":
            return self._embat_obtain_statement_data(date_since, date_until)
        return super()._obtain_statement_data(date_since, date_until)

    def _embat_request_transactions(self, date_since, date_until):
        """Method for requesting Embat transactions."""
        if not self.embat_account_bank_id:
            self._embat_get_bank_id()
        now = fields.Datetime.now()
        if now > date_since and now < date_until:
            date_until = now + datetime.timedelta(days=1)
        params = {
            "limit": 2000,
        }
        if self.embat_account_bank_id:
            params["productId"] = self.embat_account_bank_id
        if self.embat_date_type == "valued_date":
            params.update({
                "startValueDate": date_since.strftime(DF),
                "endValueDate": date_until.strftime(DF),
            })
        elif self.embat_date_type == "operation_date":
            params.update({
                "startOperationDate": date_since.strftime(DF),
                "endOperationDate": date_until.strftime(DF),
            })
        else:
            self.sudo().message_post(
                body=_(
                    "The date type for Embat import is not set correctly."
                )
            )
            return {"data": []}
        endpoint = "transactions/" + self.embat_data_id.embat_company_id
        all_transactions = []
        while True:
            _response, data = self.embat_data_id._embat_request(
                endpoint, self, params=params
            )
            if not data or "data" not in data:
                message = _("Error retrieving transactions from Embat: %s") % (_response)
                self.embat_data_id._create_log("ERROR", "ERROR", message, self)
                break
            all_transactions.extend(data.get("data") or [])
            next_page_token = data.get("nextPageToken")
            if not next_page_token:
                message = _("Transactions retrieved from Embat successfully.")
                self.embat_data_id._create_log("INFO", "INFO", message, self)
                break
            params = dict(params, nextPageToken=next_page_token)
        return {"data": all_transactions}

    def _embat_obtain_statement_data(self, date_since, date_until):
        """Called from the cron or the manual pull wizard to obtain transactions for
        the given period.
        """
        self.ensure_one()
        if not self.embat_data_id.embat_company_id:
            self.sudo().message_post(
                body=_(
                    "Please select an Embat company before importing transactions."
                )
            )
            return [], {}
        if not self.embat_account_bank_id:
            self._embat_get_bank_id()
        currency_model = self.env["res.currency"]
        statement_line_model = self.env["account.bank.statement.line"]
        is_debug = self.env.context.get("account_statement_online_import_debug")
        acc_number = self.account_number
        pull_cache = self.env.context.get("embat_pull_cache")
        pull_range = self.env.context.get("embat_pull_range")
        if pull_cache is not None and pull_range:
            if self.id not in pull_cache:
                pull_cache[self.id] = self._embat_request_transactions(
                    pull_range[0], pull_range[1]
                )
            transactions = pull_cache[self.id]
        else:
            transactions = self._embat_request_transactions(date_since, date_until)
        res = []
        sequence = 0
        currencies_cache = {}
        for transaction in (transactions or {}).get("data", []):
            if self.embat_date_type == "valued_date":
                date_str = transaction.get("valueDate") or transaction.get("operationDate")
            else:
                date_str = transaction.get("operationDate") or transaction.get("valueDate")
            if not date_str:
                continue
            try:
                date = datetime.datetime.strptime(date_str[:19], EMBAT_DATE_FORMAT)
            except (ValueError, TypeError):
                continue
            if date < date_since or (date >= date_until if date_until > date_since else date > date_until):
                continue
            status = transaction.get("status", "pending")
            if status != "BOOKED":
                continue
            product_id = (transaction.get("product") or {}).get("id", "")
            if not product_id or product_id != self.embat_account_bank_id:
                continue
            tx_id = transaction.get("id", "")
            if tx_id and not is_debug:
                check_vals = {"unique_import_id": tx_id}
                if hasattr(self.journal_id, "_statement_line_import_update_unique_import_id"):
                    self.journal_id._statement_line_import_update_unique_import_id(
                        check_vals, acc_number
                    )
                full_import_id = check_vals["unique_import_id"]
                if statement_line_model.sudo().search_count([
                    ("unique_import_id", "in", [full_import_id, tx_id]),
                    ("journal_id", "=", self.journal_id.id),
                ]):
                    continue
            sequence += 1
            amount = float(transaction.get("amount", 0.0))
            currency_code = transaction.get(
                "accountingCurrency", self.journal_id.currency_id.name
            )
            currency = currencies_cache.get(currency_code)
            if not currency:
                currency = currency_model.search([("name", "=", currency_code)])
                currencies_cache[currency_code] = currency
            amount_currency = amount
            if (
                    currency
                    and self.journal_id.currency_id
                    and currency != self.journal_id.currency_id
            ):
                amount_currency = currency._convert(
                    amount,
                    self.journal_id.currency_id,
                    self.journal_id.company_id,
                    date,
                )
            payment_ref = transaction.get("concept", "")
            res.append(
                {
                    "sequence": sequence,
                    "date": date,
                    "payment_ref": payment_ref,
                    "unique_import_id": tx_id,
                    "amount": amount_currency,
                    "account_number": acc_number,
                    "narration": str(transaction),
                }
            )

        return res, {}
