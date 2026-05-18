# Copyright 2025 Acysos S.L. (https://www.acysos.com)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
import datetime
import logging
_logger = logging.getLogger(__name__)


EMBAT_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"


class EmbatAccount(models.Model):
    _inherit = "embat.data"

    default_payment_account = fields.Many2one(
        comodel_name="account.account", string="Default Payment Account", required=True)

    def reconcile_payments_embat(self):

        companies = self.env["res.company"].search([("use_embat", "=", True)])
        for company in companies:

            embat_data_ids = self.search([("company_id", "=", company.id)])
            if not embat_data_ids:
                _logger.info("No Embat data configured for the company %s.", company.name)
                continue
            for embat_data in embat_data_ids:
                endpoint = "payments/" + embat_data.embat_company_id

                params = {"sync": False}
                request_type = "get"
                response, content = embat_data._embat_request(
                    endpoint, embat_data, request_type=request_type, params=params)

                if not content or "data" not in content:
                    message = _("Could not retrieve the payments from Embat: %s") % (response)
                    embat_data._create_log("ERROR", "PAYMENTS_ERROR", message, embat_data)
                    continue
                for payment in content["data"]:

                    if payment["type"] == "operations" and payment["operations"]:
                        embat_data.get_payment_operation(payment, company)
                    if (payment["type"] == "accountings" or
                            payment["type"] == "banks" and payment["accountingCode"] and (
                                    payment["accountingCode"].startswith("572") or
                                    payment["accountingCode"].startswith("520"))):
                        embat_data.get_payment_accounting(payment, company)
                    if payment['type'] == "contacts":
                        embat_data.get_payment_contacts(payment, company)

                message = _("Payuments synced with Embat successfully date: %s") % (
                    datetime.datetime.now().strftime(EMBAT_DATE_FORMAT))
                embat_data._create_log("INFO", "PAYMENTS_INFO", message, embat_data)

    def get_payment_operation(self, payment, company):
        _logger.info("DEBUG EMBAT PAYMENT OPERATION: %s", payment)
        move_env = self.env["account.move"]
        payment_env = self.env["account.payment"]
        journal = self.env["account.journal"].search([("embat_id", "=", payment["productId"]), ("type", "=", "bank")])

        if not journal:
            message = _("Journal not found for Embat ProudctId: %s" % payment["productId"])
            company.sudo().message_post(
                body=message
            )
            return

        for operation in payment["operations"]:
            move = move_env.search([("id", "=", int(operation["customId"].split("-")[1]))])
            _logger.info("DEBUG EMBAT MOVE: %s", move)
            _logger.info("DEBUG EMBAT MOVE Transaction ID: %s", move.embat_transaction_id)

            date = fields.Date.today()
            if "date" in payment and payment["date"]:
                date = payment["date"].split("T")[0]

            if move.payment_state == "paid":
                self.mark_as_sync(operation["customId"])

            if move.payment_state == "in_payment":
                payments_ids = self.env["account.payment"].search(
                    [("state", "=", "posted")]).filtered(
                    lambda m: move.id in m.reconciled_invoice_ids.ids)

                for payment_id in payments_ids:
                    self.reconcile_payment(
                        payment_id, move, payment.journal_id, company.id, date)
                    self.mark_as_sync(operation["customId"])
            else:
                move_payment = payment_env.search([
                    ("embat_id", "=", False), 
                    ("company_id", "=", company.id),
                    ("ref", "=", move.name),
                ])
                if move_payment:

                    move_payment.embat_id = payment["transactionId"]
                    if move.embat_transaction_id and payment["transactionId"] not in move.embat_transaction_id.split(","):
                        if move.embat_transaction_id:
                            move.embat_transaction_id += "," + payment["transactionId"] 
                        else:
                            move.embat_transaction_id = payment["transactionId"]
                    self.reconciliate_payment_embat(
                        move_payment, move, move_payment.journal_id, company, date)
                    self.mark_as_sync(payment["customId"])
                else:
                    if not move.embat_transaction_id:
                        move.embat_transaction_id = payment["transactionId"]
                    elif payment["transactionId"] not in move.embat_transaction_id.split(","):
                        move.embat_transaction_id += "," + payment["transactionId"]

                    if move.state == 'posted':
                        payment_vals = {
                            "payment_date": date,
                            "amount": abs(operation["paymentAmount"]),
                            "company_id": company.id,
                            "journal_id": journal.id,
                            "payment_difference_handling": "open",
                        }

                        move_payment = self.env["account.payment.register"].with_context(
                            active_model="account.move",
                            active_ids=move.ids
                        ).create(payment_vals)._create_payments()

                        move_payment.embat_id = payment["transactionId"]
                        move_payment.embat_transaction_id = (
                            payment["transactionId"])

                        # Force update of lines to send transactionId
                        payment_lines = move_payment.line_ids.filtered(
                            lambda line: line.account_id.user_type_id.type in
                            ['liquidity'] and line.journal_id.embat_id)
                        payment_lines._load_embat_move_line_asset()

                        self.reconciliate_payment_embat(
                            move_payment, move, journal, company, date)
                        self.mark_as_sync(payment["customId"])
                    else:
                        _logger.info(
                            "Invoice %s is not posted. Saved Embat Transaction ID "
                            "but skipping payment creation.", move.name
                        )

    def get_payment_accounting(self, payment, company):
        _logger.info("DEBUG EMBAT PAYMENT ACCOUNTING: %s", payment)
        account_debit_id = self.env["account.account"].search([("code", "=", payment["accountingCode"])])
        if not account_debit_id:
            account_id = self.default_payment_account
        journal = self.env["account.journal"].search([("embat_id", "=", payment["productId"]), ("type", "=", "bank")])
        if not journal:
            message = _("Journal not found for Embat ProudctId: %s" % payment["productId"])
            company.sudo().message_post(
                body=message
            )
            return
        else:
            account_credit_id = journal.default_account_id
            currency_id = self.env.ref("base." + payment["currency"]).id
            date = fields.Date.today()
            if "date" in payment and payment["date"]:
                date = payment["date"].split("T")[0]
            move_vals = {
                "move_type": "entry",
                "ref": payment["concept"],
                "is_move_sent": False,
                "state": "draft",
                "journal_id": journal.id,
                "company_id": company.id,
                "date": date,
                "name": "/",
                "line_ids": [],
                "embat_transaction_id": payment["transactionId"],
            }

            if payment.get("operations"):
                for operation in payment["operations"]:
                    # Use operation amount or fallback to payment logic if needed, but schema says paymentAmount exists
                    amount = operation.get("paymentAmount", 0)
                    concept = operation.get("concept", payment["concept"])
                    
                    move_vals["line_ids"].append((0, 0, {
                        "name": concept,
                        "partner_id": False,
                        "account_id": account_credit_id.id,
                        "credit": amount * -1 if amount < 0 else 0,
                        "debit": amount if amount > 0 else 0,
                        "currency_id": currency_id
                    }))
                    move_vals["line_ids"].append((0, 0, {
                        "name": concept,
                        "partner_id": False,
                        "account_id": account_debit_id.id,
                        "credit": amount if amount > 0 else 0,
                        "debit": amount * -1 if amount < 0 else 0,
                        "currency_id": currency_id
                    }))
            else:
                amount = payment.get("accountingAmount", 0)
                move_vals["line_ids"].append((0, 0, {
                    "name": payment["concept"],
                    "partner_id": False,
                    "account_id": account_credit_id.id,
                    "credit": amount * -1 if amount < 0 else 0,
                    "debit": amount if amount > 0 else 0,
                    "currency_id": currency_id
                }))
                move_vals["line_ids"].append((0, 0, {
                    "name": payment["concept"],
                    "partner_id": False,
                    "account_id": account_debit_id.id,
                    "credit": amount if amount > 0 else 0,
                    "debit": amount * -1 if amount < 0 else 0,
                    "currency_id": currency_id
                }))

            move_id = self.env["account.move"].create(move_vals)
            move_id.action_post()
            self.mark_as_sync(payment["customId"])

    def get_payment_contacts(self, payment, company):
        _logger.info("DEBUG EMBAT PAYMENT CONTACTS: %s", payment)

    def mark_as_sync(self, customid):
        endpoint = "payments/" + self.embat_company_id + "/" + customid
        request_type = "patch"
        data = {"sync": True}
        response, content = self._embat_request(endpoint, self, request_type=request_type, data=data)

    def reconciliate_payment_embat(self, payment, move, journal, company, date):
        lines_to_reconcile = self.env['account.move.line']
        payment_lines = payment.line_ids.filtered(
            lambda l: l.account_id.user_type_id.type in
            ('receivable', 'payable'))
        move_lines = move.line_ids.filtered(
            lambda l: l.account_id.user_type_id.type in
            ('receivable', 'payable'))
        lines_to_reconcile += payment_lines
        lines_to_reconcile += move_lines
        try:
            lines_to_reconcile.reconcile()
        except Exception as e:
            message = _("Error reconciling payment %s with invoice %s: %s") % (
                payment.name, move.name, str(e))
            _logger.error(message)

    def reconcile_payment(self, payment, move, journal, company, date=fields.Date.today()):
        try:
            sign = -1
            reconcile_account_id = journal.company_id.account_journal_payment_credit_account_id
            if move.move_type in ["out_invoice", "in_refund", "out_receipt"]:
                reconcile_account_id = journal.company_id.account_journal_payment_debit_account_id
                sign = 1

            st_line = self.env["account.bank.statement"].create({
                "name": move.name,
                "journal_id": journal.id,
                "company_id": company.id,
                "date": date,
                "line_ids": [(0, 0, {
                    "date": date,
                    "payment_ref": payment.name,
                    "partner_id": payment.partner_id.id,
                    "amount": payment.amount*sign
                })],
            })
            st_line.button_post()

            counterpart_line = payment.line_ids.filtered(
                lambda line: line.account_id.id == reconcile_account_id.id)
            test_st_line_1 = st_line.line_ids.filtered(
                lambda line: line.payment_ref == payment.name)
            test_st_line_1.reconcile([{"id": counterpart_line.id}])

            st_line.button_validate_or_action()
        except Exception as e:
            message = _("Cannot update EMBAT Payment because: %s" % (e))
            self.sudo().message_post(
                body=message
            )
