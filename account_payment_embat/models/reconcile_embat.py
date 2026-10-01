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

    def _parse_analytic_account(self, payment, company):
        analytic_account_id = False
        if payment.get("attributes"):
            for attr in payment.get("attributes"):
                val_id = attr.get("customId")
                if not val_id:
                    name = attr.get("name")
                    if name:
                        account = self.env["account.analytic.account"].search([
                            ("name", "=", name),
                            "|", ("company_id", "=", company.id), ("company_id", "=", False)
                        ], limit=1)
                        if not account:
                            account = self.env["account.analytic.account"].create({
                                "name": name,
                                "company_id": company.id,
                            })
                        val_id = account.id
                if val_id:
                    try:
                        analytic_account_id = int(val_id)
                        break
                    except (ValueError, TypeError):
                        pass
        return analytic_account_id


    def get_payment_operation(self, payment, company):
        _logger.info("DEBUG EMBAT PAYMENT OPERATION: %s", payment)
        move_env = self.env["account.move"]
        journal = self.env["account.journal"].search([("embat_id", "=", payment["productId"]), ("type", "=", "bank")])

        if not journal:
            message = _("Journal not found for Embat ProudctId: %s" % payment["productId"])
            company.sudo().message_post(body=message)
            return

        analytic_distribution = self._parse_analytic_distribution(payment, company)

        date = fields.Date.today()
        if "date" in payment and payment["date"]:
            date = payment["date"].split("T")[0]

        # 1. FIND THE BANK STATEMENT LINE
        transaction_id = payment.get("transactionId")
        _logger.info("Searching st_line by unique_import_id ilike %s for company %s", transaction_id, company.id)
        test_st_line_1 = self.env["account.bank.statement.line"].search(
            [("unique_import_id", "ilike", transaction_id), ("company_id", "=", company.id)], limit=1
        ) if transaction_id else False

        if not test_st_line_1:
            amount = payment.get("amount") or payment.get("accountingAmount", 0)
            if not amount and payment.get("operations"):
                amount = sum([op.get("paymentAmount", 0) for op in payment.get("operations")])
            
            domain_fallback = [
                ("amount", "in", [amount, amount * -1]),
                ("date", "=", date),
                ("journal_id", "=", journal.id),
                ("company_id", "=", company.id),
                ("is_reconciled", "=", False)
            ]
            _logger.info("Fallback search domain: %s", domain_fallback)
            st_lines = self.env["account.bank.statement.line"].search(domain_fallback)
            _logger.info("Fallback search found %s lines", len(st_lines))
            if len(st_lines) == 1:
                test_st_line_1 = st_lines[0]
            elif len(st_lines) > 1:
                st_lines_concept = st_lines.filtered(lambda l: l.payment_ref == payment.get("concept"))
                _logger.info("Filtered by concept %s found %s lines", payment.get("concept"), len(st_lines_concept))
                if len(st_lines_concept) == 1:
                    test_st_line_1 = st_lines_concept[0]

        if not test_st_line_1:
            _logger.warning("Statement line not found for operation %s", payment.get("id"))
            message = _("Statement line not found for operation payment %s") % payment.get("id")
            company.sudo().message_post(body=message)
            return
        else:
            _logger.info("Found st_line %s", test_st_line_1.id)

        if test_st_line_1.move_id.state == 'draft':
            test_st_line_1.move_id.action_post()
            
        bank_account = journal.default_account_id

        # 2. COLLECT ALL INVOICE LINES TO RECONCILE
        invoice_lines_to_reconcile = self.env['account.move.line']
        
        for operation in payment["operations"]:
            custom_id_parts = operation.get("customId", "").split("-")
            if len(custom_id_parts) < 2:
                continue
                
            move = move_env.search([("id", "=", int(custom_id_parts[1]))])
            _logger.info("DEBUG EMBAT MOVE: %s", move.name if move else "None")
            
            if move:
                transaction_id_val = payment.get("transactionId") or ""
                if not move.embat_transaction_id:
                    move.embat_transaction_id = transaction_id_val
                elif transaction_id_val not in move.embat_transaction_id.split(","):
                    move.embat_transaction_id += "," + transaction_id_val

                if move.state == 'posted' and move.payment_state != 'paid':
                    counterpart_line = move.line_ids.filtered(
                        lambda line: line.account_id.account_type in ('asset_receivable', 'liability_payable') and not line.reconciled
                    )
                    if counterpart_line:
                        invoice_lines_to_reconcile += counterpart_line[0]
                if operation.get("customId"):
                    self.mark_as_sync(operation["customId"], endpoint_type="operations")

        # 3. RECONCILE ALL
        if invoice_lines_to_reconcile:
            target_account = invoice_lines_to_reconcile[0].account_id
            
            if test_st_line_1.move_id.state == 'posted':
                test_st_line_1.move_id.button_draft()
                
            test_st_line_1.with_context(check_move_validity=False).write({
                "payment_ref": payment.get("concept", test_st_line_1.payment_ref),
                "partner_id": invoice_lines_to_reconcile[0].partner_id.id,
            })
            
            # Re-fetch suspense line because writing to test_st_line_1 might recreate move lines
            statement_move_line = test_st_line_1.move_id.line_ids.filtered(
                lambda line: line.account_id.id != bank_account.id and not line.reconciled
            )
            if len(statement_move_line) > 1:
                suspense = statement_move_line.filtered(lambda l: l.account_id.account_type not in ('asset_receivable', 'liability_payable'))
                statement_move_line = suspense[0] if suspense else statement_move_line[0]
            elif len(statement_move_line) == 1:
                statement_move_line = statement_move_line[0]
            else:
                statement_move_line = False

            if statement_move_line and statement_move_line.account_id.id != target_account.id:
                op_amount = abs(payment.get("amount") or payment.get("accountingAmount") or 0)
                if not op_amount and payment.get("operations"):
                    op_amount = abs(sum([op.get("paymentAmount", 0) for op in payment.get("operations")]))
                st_balance = statement_move_line.balance
                
                if abs(st_balance) > op_amount + 0.001:
                    alloc_debit = op_amount if st_balance > 0 else 0.0
                    alloc_credit = op_amount if st_balance < 0 else 0.0
                    rem_debit = statement_move_line.debit - alloc_debit
                    rem_credit = statement_move_line.credit - alloc_credit
                    alloc_curr = statement_move_line.amount_currency * (alloc_debit - alloc_credit) / st_balance if st_balance else 0.0
                    rem_curr = statement_move_line.amount_currency - alloc_curr
                    
                    statement_move_line.with_context(check_move_validity=False).write({
                        'debit': rem_debit,
                        'credit': rem_credit,
                        'amount_currency': rem_curr,
                    })
                    new_line_vals = {
                        'move_id': statement_move_line.move_id.id,
                        'account_id': target_account.id,
                        'partner_id': invoice_lines_to_reconcile[0].partner_id.id if invoice_lines_to_reconcile else False,
                        'name': statement_move_line.name,
                        'debit': alloc_debit,
                        'credit': alloc_credit,
                        'amount_currency': alloc_curr,
                        'currency_id': statement_move_line.currency_id.id,
                        'analytic_distribution': analytic_distribution,
                    }
                    statement_move_line = self.env['account.move.line'].with_context(check_move_validity=False).create(new_line_vals)
                else:
                    statement_move_line.with_context(check_move_validity=False).write({
                        'account_id': target_account.id,
                        'analytic_distribution': analytic_distribution
                    })
            
            if test_st_line_1.move_id.state == 'draft':
                test_st_line_1.move_id.action_post()
            
            try:
                if statement_move_line:
                    (invoice_lines_to_reconcile + statement_move_line).reconcile()
                if hasattr(test_st_line_1, 'checked'):
                    test_st_line_1.checked = True
                elif hasattr(test_st_line_1.move_id, 'checked'):
                    test_st_line_1.move_id.checked = True
                _logger.info("Successfully reconciled statement line %s with invoices", test_st_line_1.id)
            except Exception as e:
                _logger.error("Error reconciling statement %s: %s", test_st_line_1.id, e)
                message = _("Error reconciling operation payment %s: %s") % (payment.get("id"), str(e))
                company.sudo().message_post(body=message)



    def get_payment_accounting(self, payment, company):
        _logger.info("DEBUG EMBAT PAYMENT ACCOUNTING: %s", payment)
        account_debit_id = self.env["account.account"].search([("code", "=", payment["accountingCode"]), ("company_id", "=", company.id)], limit=1)
        if not account_debit_id:
            account_debit_id = self.default_payment_account
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

            analytic_account_id = self._parse_analytic_account(payment, company)

            transaction_id = payment.get("transactionId")
            _logger.info("Searching st_line by unique_import_id ilike %s for company %s", transaction_id, company.id)
            st_line = self.env["account.bank.statement.line"].search(
                [("unique_import_id", "ilike", transaction_id), ("company_id", "=", company.id)], limit=1
            ) if transaction_id else False

            if not st_line:
                amount = payment.get("accountingAmount", 0)
                if not amount and payment.get("operations"):
                    amount = sum([op.get("paymentAmount", 0) for op in payment.get("operations")])
                
                domain_fallback = [
                    ("amount", "=", amount),
                    ("date", "=", date),
                    ("journal_id", "=", journal.id),
                    ("company_id", "=", company.id),
                    ("is_reconciled", "=", False)
                ]
                _logger.info("Fallback search domain: %s", domain_fallback)
                st_lines = self.env["account.bank.statement.line"].search(domain_fallback)
                _logger.info("Fallback search found %s lines", len(st_lines))
                if len(st_lines) == 1:
                    st_line = st_lines[0]
                elif len(st_lines) > 1:
                    st_lines_concept = st_lines.filtered(lambda l: l.payment_ref == payment.get("concept"))
                    _logger.info("Filtered by concept %s found %s lines", payment.get("concept"), len(st_lines_concept))
                    if len(st_lines_concept) == 1:
                        st_line = st_lines_concept[0]

            if not st_line:
                _logger.warning("Statement line not found for payment %s", payment.get("id"))
                message = _("Statement line not found for payment %s") % payment.get("id")
                company.sudo().message_post(body=message)
                return
            else:
                _logger.info("Found st_line %s", st_line.id)

            if st_line:
                if st_line.state == 'draft':
                    st_line.statement_id.button_post()
                
                reconcile_vals = [{"account_id": account_debit_id.id}]
                if analytic_account_id:
                    reconcile_vals[0]["analytic_account_id"] = analytic_account_id
                
                st_line.reconcile(reconcile_vals)
                if hasattr(st_line.statement_id, 'button_validate_or_action'):
                    st_line.statement_id.button_validate_or_action()
                
                self.mark_as_sync(payment["customId"])
                return



    def get_payment_contacts(self, payment, company):
        _logger.info("DEBUG EMBAT PAYMENT CONTACTS: %s", payment)
        
        analytic_distribution = self._parse_analytic_distribution(payment, company)
        
        partner = False
        partner_id_str = payment.get("contactCustomId")
        if partner_id_str:
            try:
                partner = self.env["res.partner"].browse(int(partner_id_str))
                if not partner.exists():
                    partner = False
            except ValueError:
                partner = False

        if not partner and payment.get("contact"):
            contact_data = payment["contact"]
            custom_id = contact_data.get("customId")
            if custom_id:
                try:
                    partner = self.env["res.partner"].browse(int(custom_id))
                    if not partner.exists():
                        partner = False
                except ValueError:
                    partner = False
            if not partner and contact_data.get("id"):
                partner = self.env["res.partner"].search([("embat_id", "=", contact_data["id"])], limit=1)
            if not partner and contact_data.get("taxId"):
                partner = self.env["res.partner"].search([("vat", "=", contact_data["taxId"])], limit=1)

        if not partner:
            message = _("Contact not found for Embat payment: %s") % payment.get("id")
            company.sudo().message_post(body=message)
            return

        journal = self.env["account.journal"].search([("embat_id", "=", payment["productId"]), ("type", "=", "bank")])
        if not journal:
            message = _("Journal not found for Embat ProductId: %s") % payment["productId"]
            company.sudo().message_post(body=message)
            return

        date = fields.Date.today()
        if "date" in payment and payment["date"]:
            date = payment["date"].split("T")[0]

        amount = payment.get("accountingAmount") or payment.get("amount") or 0
        if not amount:
            return

        payment_type = "inbound" if amount > 0 else "outbound"
        destination_account = partner.property_account_receivable_id if payment_type == "inbound" else partner.property_account_payable_id

        # FIND STATEMENT LINE
        transaction_id = payment.get("transactionId")
        _logger.info("Searching st_line by unique_import_id ilike %s for company %s", transaction_id, company.id)
        test_st_line_1 = self.env["account.bank.statement.line"].search(
            [("unique_import_id", "ilike", transaction_id), ("company_id", "=", company.id)], limit=1
        ) if transaction_id else False

        if not test_st_line_1:
            st_line_amount = abs(amount) * (1 if payment_type == "inbound" else -1)
            domain_fallback = [
                ("amount", "in", [st_line_amount, st_line_amount * -1]),
                ("date", "=", date),
                ("journal_id", "=", journal.id),
                ("company_id", "=", company.id),
                ("is_reconciled", "=", False)
            ]
            _logger.info("Fallback search domain: %s", domain_fallback)
            st_lines = self.env["account.bank.statement.line"].search(domain_fallback)
            _logger.info("Fallback search found %s lines", len(st_lines))
            if len(st_lines) == 1:
                test_st_line_1 = st_lines[0]
            elif len(st_lines) > 1:
                st_lines_concept = st_lines.filtered(lambda l: l.payment_ref == payment.get("concept"))
                _logger.info("Filtered by concept %s found %s lines", payment.get("concept"), len(st_lines_concept))
                if len(st_lines_concept) == 1:
                    test_st_line_1 = st_lines_concept[0]

        if not test_st_line_1:
            _logger.warning("Statement line not found for contact payment %s", payment.get("id"))
            message = _("Statement line not found for contact payment %s") % payment.get("id")
            company.sudo().message_post(body=message)
            return
        else:
            _logger.info("Found st_line %s", test_st_line_1.id)

        # UPDATE STATEMENT LINE
        bank_account = journal.default_account_id
        
        if test_st_line_1.move_id.state == 'posted':
            test_st_line_1.move_id.button_draft()
            
        test_st_line_1.with_context(check_move_validity=False).write({
            "payment_ref": payment.get("concept", test_st_line_1.payment_ref),
            "partner_id": partner.id,
        })
        
        statement_move_line = test_st_line_1.move_id.line_ids.filtered(
            lambda line: line.account_id.id != bank_account.id and not line.reconciled
        )
        if len(statement_move_line) > 1:
            suspense = statement_move_line.filtered(lambda l: l.account_id.account_type not in ('asset_receivable', 'liability_payable'))
            statement_move_line = suspense[0] if suspense else statement_move_line[0]
        elif len(statement_move_line) == 1:
            statement_move_line = statement_move_line[0]
        else:
            statement_move_line = False
            
        if statement_move_line:
            op_amount = abs(amount)
            st_balance = statement_move_line.balance
            
            if abs(st_balance) > op_amount + 0.001:
                alloc_debit = op_amount if st_balance > 0 else 0.0
                alloc_credit = op_amount if st_balance < 0 else 0.0
                rem_debit = statement_move_line.debit - alloc_debit
                rem_credit = statement_move_line.credit - alloc_credit
                alloc_curr = statement_move_line.amount_currency * (alloc_debit - alloc_credit) / st_balance if st_balance else 0.0
                rem_curr = statement_move_line.amount_currency - alloc_curr
                
                statement_move_line.with_context(check_move_validity=False).write({
                    'debit': rem_debit,
                    'credit': rem_credit,
                    'amount_currency': rem_curr,
                })
                new_line_vals = {
                    'move_id': statement_move_line.move_id.id,
                    'account_id': destination_account.id,
                    'partner_id': partner.id,
                    'name': statement_move_line.name,
                    'debit': alloc_debit,
                    'credit': alloc_credit,
                    'amount_currency': alloc_curr,
                    'currency_id': statement_move_line.currency_id.id,
                    'analytic_distribution': analytic_distribution,
                }
                statement_move_line = self.env['account.move.line'].with_context(check_move_validity=False).create(new_line_vals)
            else:
                statement_move_line.with_context(check_move_validity=False).write({
                    'account_id': destination_account.id,
                    'partner_id': partner.id,
                    'analytic_distribution': analytic_distribution,
                })
            
        if test_st_line_1.move_id.state == 'draft':
            test_st_line_1.move_id.action_post()
            if hasattr(test_st_line_1, 'checked'):
                test_st_line_1.checked = True
            elif hasattr(test_st_line_1.move_id, 'checked'):
                test_st_line_1.move_id.checked = True
                
        self.mark_as_sync(payment["customId"])

    def mark_as_sync(self, customid):
        endpoint = "payments/" + self.embat_company_id + "/" + customid
        _logger.info("Endpoint: %s", endpoint)
        request_type = "patch"
        data = {"sync": "true"}
        _logger.info("Data: %s", data)
        try:
            import inspect
            if 'fallback_on_404' in inspect.signature(self._embat_request).parameters:
                response, content = self._embat_request(endpoint, self, request_type=request_type, data=data, fallback_on_404=False)
            else:
                response, content = self._embat_request(endpoint, self, request_type=request_type, data=data)
            _logger.info("Response: %s", response)
            _logger.info("Content: %s", content)
        except Exception as e:
            _logger.warning("Failed to mark payment %s as synced on Embat (it may have been deleted). Error: %s", customid, str(e))

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

    def reconcile_payment(self, payment, move, journal, company, date=fields.Date.today(), transaction_id=False):
        try:
            sign = -1
            reconcile_account_id = journal.company_id.account_journal_payment_credit_account_id
            if move.move_type in ["out_invoice", "in_refund", "out_receipt"]:
                reconcile_account_id = journal.company_id.account_journal_payment_debit_account_id
                sign = 1

            company_id = company.id if isinstance(company, models.Model) else company


            test_st_line_1 = False
            _logger.info("Searching st_line by unique_import_id ilike %s for company %s", transaction_id, company_id)
            if transaction_id:
                test_st_line_1 = self.env["account.bank.statement.line"].search(
                    [("unique_import_id", "ilike", transaction_id), ("company_id", "=", company_id)], limit=1
                )
            
            if not test_st_line_1:
                st_line_amount = payment.amount * sign
                domain_fallback = [
                    ("amount", "=", st_line_amount),
                    ("date", "=", date),
                    ("journal_id", "=", journal.id),
                    ("company_id", "=", company_id),
                    ("is_reconciled", "=", False)
                ]
                _logger.info("Fallback search domain: %s", domain_fallback)
                st_lines = self.env["account.bank.statement.line"].search(domain_fallback)
                _logger.info("Fallback search found %s lines", len(st_lines))
                if len(st_lines) == 1:
                    test_st_line_1 = st_lines[0]
                elif len(st_lines) > 1:
                    st_lines_concept = st_lines.filtered(lambda l: l.payment_ref == payment.name)
                    _logger.info("Filtered by concept %s found %s lines", payment.name, len(st_lines_concept))
                    if len(st_lines_concept) == 1:
                        test_st_line_1 = st_lines_concept[0]

            if not test_st_line_1:
                _logger.warning("Statement line not found for payment %s", payment.name)
                message = _("Statement line not found for payment %s") % payment.name
                company.sudo().message_post(body=message)
                return
            else:
                _logger.info("Found st_line %s", test_st_line_1.id)

            if test_st_line_1:
                if test_st_line_1.move_id.state == 'posted':
                    test_st_line_1.move_id.button_draft()
                test_st_line_1.with_context(check_move_validity=False).write({
                    "payment_ref": payment.name,
                    "partner_id": payment.partner_id.id,
                })
                # It will be posted later below if needed, or we post it now
                if test_st_line_1.move_id.state == 'draft':
                    test_st_line_1.move_id.action_post()
                if test_st_line_1.state == 'draft':
                    test_st_line_1.statement_id.button_post()

                counterpart_line = payment.line_ids.filtered(
                    lambda line: line.account_id.id == reconcile_account_id.id)
                test_st_line_1.reconcile([{"id": counterpart_line.id}])

                if hasattr(test_st_line_1.statement_id, 'button_validate_or_action'):
                    test_st_line_1.statement_id.button_validate_or_action()
        except Exception as e:
            message = _("Cannot update EMBAT Payment because: %s" % (e))
            self.sudo().message_post(
                body=message
            )
