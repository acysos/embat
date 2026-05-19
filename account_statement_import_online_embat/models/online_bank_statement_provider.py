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
        self.ensure_one()
        if self.embat_data_id:
            endpoint = "banks/" + self.embat_data_id.embat_company_id
            response, content = self.embat_data_id._embat_request(endpoint, self)
            if not content or "data" not in content:
                message = _("Could not retrieve the list of banks from Embat: %s") % (response)
                self.embat_data_id._create_log("ERROR", "ERROR", message, self)
                raise UserError(message)
            message = _("List of banks retrieved from Embat successfully.")
            self.embat_data_id._create_log("INFO", "INFO", message, self)
            acc_number = self.account_number.lower() or False
            if acc_number:
                for bank in content["data"]:
                    for bankproduct in bank.get("bankProducts", []):
                        accountnumber = bankproduct.get("accountNumber")
                        accountnumber = accountnumber.lower() if accountnumber else ""
                        if accountnumber == acc_number:
                            self.embat_account_bank_id = bankproduct["id"]
                    if not self.embat_account_bank_id:
                        raise UserError(_("The bank was not found in Embat."))
            else:
                raise UserError(_("No bank account in journal"))


    def _obtain_statement_data(self, date_since, date_until):
        """Generic online cron overrided for acting when the sync is for GoCardless."""
        self.ensure_one()
        if self.service == "embat":
            return self._embat_obtain_statement_data(date_since, date_until)
        return super()._obtain_statement_data(date_since, date_until)

    def _embat_request_transactions(self, date_since, date_until):
        """Method for requesting Embat transactions."""
        now = fields.Datetime.now()
        if now > date_since and now < date_until:
            date_until = now
        params = {}
        if self.embat_date_type == "valued_date":
            params.update({
                "startValueDate": date_since.strftime(DF),
                "endValueDate": date_until.strftime(DF),
            })
        elif self.embat_date_type == "operation_date":
            params.update({
                "productID": self.embat_account_bank_id,
                "startOperationDate": date_since.strftime(DF),
                "endOperationDate": date_until.strftime(DF),
            })
        else:
            self.sudo().message_post(
                body=_(
                    "The date type for Embat import is not set correctly."
                )
            )
        endpoint = "transactions/" + self.embat_data_id.embat_company_id
        _response, data = self.embat_data_id._embat_request(endpoint, self, params=params)
        if not data or "id" not in data:
            message = _("Error retrieving transactions from Embat: %s") % (_response)
            self.embat_data_id._create_log("ERROR", "ERROR", message, self)
        message = _("Transactions retrieved from Embat successfully.")
        self.embat_data_id._create_log("INFO", "INFO", message, self)
        return data

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
        currency_model = self.env["res.currency"]
        acc_number = self.account_number
        transactions = self._embat_request_transactions(date_since, date_until)
        res = []
        sequence = 0
        currencies_cache = {}
        for transaction in transactions.get("data", []):
            if self.embat_date_type == "valued_date":
                date = datetime.datetime.strptime(transaction.get("valueDate", ""), EMBAT_DATE_FORMAT)
            else:
                date = datetime.datetime.strptime(transaction.get("operationDate", ""), EMBAT_DATE_FORMAT)
            if not date:
                continue
            if date < date_since or date > date_until:
                continue
            status = transaction.get("status", "pending")
            if status != "BOOKED":
                continue
            product_id = transaction.get("product", "").get("id", "")
            if not product_id or product_id != self.embat_account_bank_id:
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
                    "unique_import_id": transaction.get("id", ""),
                    "amount": amount_currency,
                    "account_number": acc_number,
                    "narration": str(transaction),
                }
            )

        return res, {}
