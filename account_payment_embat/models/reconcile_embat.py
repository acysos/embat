# Copyright 2025 Acysos S.L. (https://www.acysos.com)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
import datetime
import logging
import inspect

_logger = logging.getLogger(__name__)


EMBAT_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"


class EmbatAccount(models.Model):
    _inherit = "embat.data"

    default_payment_account = fields.Many2one(
        comodel_name="account.account", string="Default Payment Account"
    )

    def reconcile_payments_embat(self):
        companies = self.env["res.company"].search([("use_embat", "=", True)])
        for company in companies:
            embat_data_ids = self.search([("company_id", "=", company.id)])
            if not embat_data_ids:
                _logger.info("No Embat data configured for the company %s.", company.name)
                continue
            for embat_data in embat_data_ids:
                embat_data_company = embat_data.with_company(company)
                endpoint = "payments/" + embat_data.embat_company_id

                params = {"sync": False}
                request_type = "get"
                all_payments = []
                next_page_token = None
                fetch_failed = False

                while True:
                    req_params = dict(params)
                    if next_page_token:
                        req_params["nextPageToken"] = next_page_token
                    response, content = embat_data_company._embat_request(
                        endpoint, embat_data_company, request_type=request_type, params=req_params
                    )
                    if not content or "data" not in content:
                        if not all_payments:
                            message = _("Could not retrieve the payments from Embat: %s") % (response)
                            embat_data_company._create_log(
                                "ERROR", "PAYMENTS_ERROR", message, embat_data_company
                            )
                            fetch_failed = True
                        break
                    all_payments.extend(content.get("data") or [])
                    next_page_token = content.get("nextPageToken")
                    if not next_page_token:
                        break

                if fetch_failed:
                    continue

                for payment in all_payments:
                    ptype = payment.get("type")
                    pcode = payment.get("accountingCode")
                    if ptype == "operations" and payment.get("operations"):
                        embat_data_company.get_payment_operation(payment, company)
                    if (
                        ptype == "accountings"
                        or (
                            ptype == "banks"
                            and pcode
                            and (pcode.startswith("572") or pcode.startswith("520"))
                        )
                    ):
                        embat_data_company.get_payment_accounting(payment, company)
                    if ptype == "contacts":
                        embat_data_company.get_payment_contacts(payment, company)

                message = _("Payuments synced with Embat successfully date: %s") % (
                    datetime.datetime.now().strftime(EMBAT_DATE_FORMAT)
                )
                embat_data_company._create_log(
                    "INFO", "PAYMENTS_INFO", message, embat_data_company
                )

    def _parse_analytic_distribution(self, payment, company):
        analytic_distribution = {}
        if payment.get("attributes"):
            for attr in payment.get("attributes"):
                val_id = attr.get("valueCustomId")
                if not val_id:
                    name = attr.get("value") or attr.get("name")
                    if name:
                        account = self.env["account.analytic.account"].search(
                            [
                                ("name", "=", name),
                                "|",
                                ("company_id", "=", company.id),
                                ("company_id", "=", False),
                            ],
                            limit=1,
                        )
                        if not account:
                            account = self.env["account.analytic.account"].create(
                                {
                                    "name": name,
                                    "company_id": company.id,
                                }
                            )
                        val_id = account.id
                if val_id:
                    try:
                        analytic_distribution[str(int(val_id))] = 100.0
                    except (ValueError, TypeError):
                        pass
        return analytic_distribution

    def _resolve_embat_partner(self, payment):
        partner = False
        partner_id_str = payment.get("contactCustomId")
        if partner_id_str:
            try:
                partner = self.env["res.partner"].browse(int(partner_id_str))
                if not partner.exists():
                    partner = False
            except (ValueError, TypeError):
                partner = False

        if not partner and payment.get("contact"):
            contact_data = payment["contact"]
            custom_id = contact_data.get("customId")
            if custom_id:
                try:
                    partner = self.env["res.partner"].browse(int(custom_id))
                    if not partner.exists():
                        partner = False
                except (ValueError, TypeError):
                    partner = False
            if not partner and contact_data.get("id"):
                partner = self.env["res.partner"].search(
                    [("embat_id", "=", contact_data["id"])], limit=1
                )
            if not partner and contact_data.get("taxId"):
                partner = self.env["res.partner"].search(
                    [("vat", "=", contact_data["taxId"])], limit=1
                )
        return partner

    def _get_signed_payment_company_amount(self, payment):
        raw_acc = payment.get("accountingAmount")
        raw_amt = payment.get("amount")
        if raw_acc not in (None, 0, 0.0):
            return float(raw_acc)
        if raw_amt not in (None, 0, 0.0):
            return float(raw_amt)
        if payment.get("operations"):
            return float(
                sum(
                    (
                        op.get("paymentAmount")
                        or op.get("operationPaymentAmount")
                        or op.get("amount")
                        or 0.0
                    )
                    for op in payment["operations"]
                )
            )
        return 0.0

    def _find_embat_statement_line(self, payment, journal, company, date):
        transaction_id = payment.get("transactionId")
        _logger.info(
            "Searching st_line by unique_import_id ilike %s for company %s",
            transaction_id,
            company.id,
        )
        st_line = False
        if transaction_id:
            st_line = self.env["account.bank.statement.line"].search(
                [
                    ("unique_import_id", "ilike", transaction_id),
                    ("journal_id", "=", journal.id),
                    ("company_id", "=", company.id),
                ],
                limit=1,
            )
            if not st_line:
                st_line = self.env["account.bank.statement.line"].search(
                    [
                        ("unique_import_id", "ilike", transaction_id),
                        ("company_id", "=", company.id),
                    ],
                    limit=1,
                )

        if not st_line:
            candidate_amounts = []
            tx_amt = (
                payment.get("transactionAccountingAmount")
                if payment.get("transactionAccountingAmount") not in (None, 0, 0.0)
                else payment.get("transactionAmount")
            )
            if tx_amt not in (None, 0, 0.0):
                tx_amt = float(tx_amt)
                candidate_amounts.extend([tx_amt, -tx_amt])

            pay_amt = self._get_signed_payment_company_amount(payment)
            if pay_amt:
                candidate_amounts.extend([pay_amt, -pay_amt])

            if candidate_amounts:
                domain_fallback = [
                    ("amount", "in", list(dict.fromkeys(candidate_amounts))),
                    ("date", "=", date),
                    ("journal_id", "=", journal.id),
                    ("company_id", "=", company.id),
                    ("is_reconciled", "=", False),
                ]
                _logger.info("Fallback search domain: %s", domain_fallback)
                st_lines = self.env["account.bank.statement.line"].search(domain_fallback)
                _logger.info("Fallback search found %s lines", len(st_lines))
                if len(st_lines) == 1:
                    st_line = st_lines[0]
                elif len(st_lines) > 1:
                    st_lines_concept = st_lines.filtered(
                        lambda l: l.payment_ref == payment.get("concept")
                    )
                    _logger.info(
                        "Filtered by concept %s found %s lines",
                        payment.get("concept"),
                        len(st_lines_concept),
                    )
                    if len(st_lines_concept) == 1:
                        st_line = st_lines_concept[0]

        return st_line

    def _compute_embat_counterpart_amounts(
        self, signed_company_amount, company, date, raw_foreign_amount=None, target_currency=None
    ):
        """Convert a signed Embat payment amount (negative = bank outflow, positive = bank inflow)
        into counterpart journal item amounts on the bank statement move:
          - Outbound (-X) -> counterpart balance +X (Debit X)
          - Inbound  (+X) -> counterpart balance -X (Credit X)
        """
        company_currency = company.currency_id
        counterpart_balance = company_currency.round(-float(signed_company_amount))
        debit = counterpart_balance if counterpart_balance > 0 else 0.0
        credit = -counterpart_balance if counterpart_balance < 0 else 0.0

        if target_currency and target_currency != company_currency:
            line_currency = target_currency
            if raw_foreign_amount not in (None, 0, 0.0):
                amount_currency = target_currency.round(-float(raw_foreign_amount))
            else:
                amount_currency = company_currency._convert(
                    counterpart_balance, target_currency, company, date
                )
        else:
            line_currency = company_currency
            amount_currency = counterpart_balance

        return {
            "debit": debit,
            "credit": credit,
            "currency_id": line_currency.id,
            "amount_currency": amount_currency,
        }

    def _dispatch_statement_move_lines(self, st_line, journal):
        if hasattr(st_line, "_seek_for_lines"):
            liquidity_lines, suspense_lines, other_lines = st_line._seek_for_lines()
            reconciled_suspense = suspense_lines.filtered(lambda l: l.reconciled)
            if reconciled_suspense:
                other_lines |= reconciled_suspense
                suspense_lines -= reconciled_suspense
        else:
            bank_account = journal.default_account_id
            suspense_account = journal.suspense_account_id
            liquidity_lines = st_line.move_id.line_ids.filtered(
                lambda l: l.account_id == bank_account
            )
            suspense_lines = st_line.move_id.line_ids.filtered(
                lambda l: suspense_account
                and l.account_id == suspense_account
                and not l.reconciled
            )
            other_lines = st_line.move_id.line_ids - liquidity_lines - suspense_lines

        if not suspense_lines and not other_lines:
            fallback_suspense = (st_line.move_id.line_ids - liquidity_lines).filtered(
                lambda l: not l.reconciled
                and l.account_id.account_type not in ("asset_receivable", "liability_payable")
            )
            suspense_lines = fallback_suspense

        return liquidity_lines, suspense_lines, other_lines

    def _record_move_transaction_id(self, move, transaction_id):
        if not move or not transaction_id:
            return
        existing = [
            t.strip() for t in (move.embat_transaction_id or "").split(",") if t.strip()
        ]
        if transaction_id not in existing:
            existing.append(transaction_id)
            move.with_context(skip_embat_sync=True).embat_transaction_id = ",".join(existing)

    def _apply_embat_lines_to_statement_line(
        self,
        st_line,
        journal,
        company,
        new_lines_spec,
        concept=False,
        transaction_id=False,
        error_context_id=False,
    ):
        """Add one or more counterpart journal items to `st_line.move_id` while preserving
        any already-created or already-reconciled counterpart lines from previous elements
        of the same bank transaction, recalculating or removing the suspense line as needed.
        """
        if not new_lines_spec:
            return

        if st_line.move_id.state == "draft":
            st_line.move_id.action_post()

        self._record_move_transaction_id(st_line.move_id, transaction_id)

        liquidity_lines, suspense_lines, other_lines = self._dispatch_statement_move_lines(
            st_line, journal
        )
        kept_lines = liquidity_lines + other_lines

        company_currency = company.currency_id
        journal_currency = journal.currency_id or company_currency
        suspense_currency = st_line.foreign_currency_id or journal_currency

        kept_balance = sum(kept_lines.mapped("balance"))
        added_balance = sum(spec["debit"] - spec["credit"] for spec in new_lines_spec)
        remaining_to_balance = company_currency.round(-(kept_balance + added_balance))

        partner_ids = set(other_lines.mapped("partner_id").ids) | {
            spec["partner_id"] for spec in new_lines_spec if spec.get("partner_id")
        }
        if len(partner_ids) == 1:
            resolved_partner_id = next(iter(partner_ids))
        elif len(partner_ids) > 1:
            resolved_partner_id = False
        else:
            resolved_partner_id = st_line.partner_id.id or False

        if not other_lines:
            new_payment_ref = concept or st_line.payment_ref
        else:
            new_payment_ref = st_line.payment_ref or concept

        line_commands = []
        if len(liquidity_lines) == 1 and not liquidity_lines.reconciled:
            liq_updates = {}
            if new_payment_ref and liquidity_lines.name != new_payment_ref:
                liq_updates["name"] = new_payment_ref
            if liquidity_lines.partner_id.id != (resolved_partner_id or False):
                liq_updates["partner_id"] = resolved_partner_id
            if liq_updates:
                line_commands.append((1, liquidity_lines.id, liq_updates))

        for s_line in suspense_lines:
            line_commands.append((2, s_line.id))

        for spec in new_lines_spec:
            aml_vals = {
                "name": spec.get("name") or new_payment_ref or "/",
                "account_id": spec["account_id"],
                "partner_id": spec.get("partner_id") or False,
                "currency_id": spec["currency_id"],
                "amount_currency": spec["amount_currency"],
                "debit": spec["debit"],
                "credit": spec["credit"],
            }
            if spec.get("analytic_distribution"):
                aml_vals["analytic_distribution"] = spec["analytic_distribution"]
            line_commands.append((0, 0, aml_vals))

        if not company_currency.is_zero(remaining_to_balance):
            suspense_account = journal.suspense_account_id or (
                suspense_lines[0].account_id if suspense_lines else journal.default_account_id
            )
            if suspense_currency == company_currency:
                suspense_amount_currency = remaining_to_balance
            else:
                all_same_curr = (
                    all(l.currency_id == suspense_currency for l in kept_lines)
                    and all(s["currency_id"] == suspense_currency.id for s in new_lines_spec)
                )
                if all_same_curr:
                    suspense_amount_currency = suspense_currency.round(
                        -(
                            sum(kept_lines.mapped("amount_currency"))
                            + sum(s["amount_currency"] for s in new_lines_spec)
                        )
                    )
                else:
                    suspense_amount_currency = company_currency._convert(
                        remaining_to_balance,
                        suspense_currency,
                        company,
                        st_line.date or fields.Date.today(),
                    )
            suspense_vals = {
                "name": new_payment_ref or st_line.payment_ref or "/",
                "account_id": suspense_account.id,
                "partner_id": False,
                "currency_id": suspense_currency.id,
                "amount_currency": suspense_amount_currency,
                "debit": remaining_to_balance if remaining_to_balance > 0 else 0.0,
                "credit": -remaining_to_balance if remaining_to_balance < 0 else 0.0,
            }
            line_commands.append((0, 0, suspense_vals))

        existing_ids = set(kept_lines.ids)
        move_ctx = st_line.move_id.with_context(
            force_delete=True,
            skip_readonly_check=True,
            skip_account_move_synchronization=True,
            skip_embat_sync=True,
        )
        move_ctx.write(
            {
                "partner_id": resolved_partner_id,
                "line_ids": line_commands,
            }
        )

        st_line.with_context(
            skip_account_move_synchronization=True,
            skip_readonly_check=True,
        ).write(
            {
                "payment_ref": new_payment_ref,
                "partner_id": resolved_partner_id,
            }
        )

        if st_line.move_id.state == "draft":
            st_line.move_id.with_context(skip_embat_sync=True).action_post()

        all_new_lines = st_line.move_id.line_ids.filtered(
            lambda l: l.id not in existing_ids
        ).sorted("id")
        created_counterpart_lines = all_new_lines[: len(new_lines_spec)]

        for created_line, spec in zip(created_counterpart_lines, new_lines_spec):
            inv_lines = spec.get("reconcile_lines")
            if inv_lines:
                try:
                    lines_to_rec = (created_line + inv_lines).filtered(
                        lambda l: not l.reconciled
                    )
                    if len(lines_to_rec) > 1:
                        lines_to_rec.reconcile()
                except Exception as e:
                    _logger.error("Error reconciling statement %s: %s", st_line.id, e)
                    message = _("Error reconciling operation payment %s: %s") % (
                        error_context_id or "",
                        str(e),
                    )
                    company.sudo().message_post(body=message)

        if hasattr(st_line, "checked"):
            st_line.with_context(
                skip_account_move_synchronization=True, skip_readonly_check=True
            ).checked = True
        elif hasattr(st_line.move_id, "checked"):
            st_line.move_id.with_context(
                skip_account_move_synchronization=True, skip_readonly_check=True
            ).checked = True
        if hasattr(st_line.move_id, "to_check") and st_line.move_id.to_check:
            st_line.move_id.with_context(
                skip_account_move_synchronization=True, skip_readonly_check=True
            ).to_check = False

        has_suspense = any(
            l.account_id
            and journal.suspense_account_id
            and l.account_id == journal.suspense_account_id
            for l in st_line.move_id.line_ids
        )
        if not has_suspense and liquidity_lines:
            liquidity_lines._load_embat_move_line_asset()

    def get_payment_operation(self, payment, company):
        _logger.info("DEBUG EMBAT PAYMENT OPERATION: %s", payment)
        move_env = self.env["account.move"]
        journal = self.env["account.journal"].search(
            [
                ("embat_id", "=", payment["productId"]),
                ("type", "=", "bank"),
                ("company_id", "=", company.id),
            ],
            limit=1,
        )

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
        test_st_line_1 = self._find_embat_statement_line(payment, journal, company, date)

        if not test_st_line_1:
            _logger.warning("Statement line not found for operation %s", payment.get("id"))
            message = _("Statement line not found for operation payment %s") % payment.get("id")
            company.sudo().message_post(body=message)
            return
        _logger.info("Found st_line %s", test_st_line_1.id)

        # 2. COLLECT ALL INVOICE OPERATIONS TO RECONCILE
        valid_ops = []
        bank_account = journal.default_account_id

        for operation in payment.get("operations") or []:
            custom_id_parts = operation.get("customId", "").split("-")
            if len(custom_id_parts) < 2:
                continue
            try:
                move_id_int = int(custom_id_parts[1])
            except (ValueError, TypeError):
                continue

            move = move_env.search([("id", "=", move_id_int)], limit=1)
            _logger.info("DEBUG EMBAT MOVE: %s", move.name if move else "None")

            if move:
                self._record_move_transaction_id(move, transaction_id)

                if move.state == "posted":
                    counterpart_lines = move.line_ids.filtered(
                        lambda line: line.account_id.account_type
                        in ("asset_receivable", "liability_payable")
                        and not line.reconciled
                    ).sorted(key=lambda l: (l.date_maturity or fields.Date.today(), l.id))
                    if counterpart_lines:
                        target_account = counterpart_lines[0].account_id
                        counterpart_lines = counterpart_lines.filtered(
                            lambda l, acc=target_account: l.account_id == acc
                        )
                        valid_ops.append(
                            {
                                "operation": operation,
                                "move": move,
                                "target_account": target_account,
                                "reconcile_lines": counterpart_lines,
                            }
                        )
                    else:
                        # Check if invoice was paid via an Odoo account.payment with an open outstanding line
                        all_rp_lines = move.line_ids.filtered(
                            lambda line: line.account_id.account_type
                            in ("asset_receivable", "liability_payable")
                        )
                        matched_lines = (
                            all_rp_lines.matched_debit_ids.debit_move_id
                            + all_rp_lines.matched_credit_ids.credit_move_id
                        )
                        outstanding_lines = matched_lines.mapped("move_id.line_ids").filtered(
                            lambda l: l.account_id != bank_account
                            and l.account_id.account_type
                            not in ("asset_receivable", "liability_payable")
                            and l.account_id.reconcile
                            and not l.reconciled
                        )
                        if outstanding_lines:
                            target_account = outstanding_lines[0].account_id
                            outstanding_lines = outstanding_lines.filtered(
                                lambda l, acc=target_account: l.account_id == acc
                            )
                            valid_ops.append(
                                {
                                    "operation": operation,
                                    "move": move,
                                    "target_account": target_account,
                                    "reconcile_lines": outstanding_lines,
                                }
                            )

        # 3. BUILD COUNTERPART LINES & RECONCILE PRESERVING EXISTING SPLIT LINES
        if valid_ops:
            total_signed_company_amt = self._get_signed_payment_company_amount(payment)
            raw_pay_amt = payment.get("amount")
            pay_currency_code = payment.get("currency")
            pay_currency = (
                self.env["res.currency"].search([("name", "=", pay_currency_code)], limit=1)
                if pay_currency_code
                else False
            )

            # Ratio to convert operation amounts to company currency if multi-currency
            conv_ratio = 1.0
            if (
                raw_pay_amt not in (None, 0, 0.0)
                and payment.get("accountingAmount") not in (None, 0, 0.0)
            ):
                conv_ratio = float(payment["accountingAmount"]) / float(raw_pay_amt)

            new_lines_spec = []
            concept = payment.get("concept")
            allocated_so_far = 0.0

            for idx, item in enumerate(valid_ops):
                op = item["operation"]
                move = item["move"]
                rec_lines = item["reconcile_lines"]
                target_account = item["target_account"]
                inv_currency = rec_lines[0].currency_id or company.currency_id

                if len(valid_ops) == 1:
                    op_company_signed = total_signed_company_amt
                    if not op_company_signed:
                        # Fallback to open residual on invoice (same sign as Embat payment: -(-residual) = residual)
                        op_company_signed = sum(rec_lines.mapped("amount_residual"))
                    if (
                        op.get("currency") == inv_currency.name
                        and op.get("amount") not in (None, 0, 0.0)
                    ):
                        op_foreign_raw = float(op["amount"])
                    elif pay_currency and pay_currency == inv_currency:
                        op_foreign_raw = raw_pay_amt
                    elif (
                        inv_currency != company.currency_id
                        and company.currency_id.compare_amounts(
                            op_company_signed, sum(rec_lines.mapped("amount_residual"))
                        )
                        == 0
                    ):
                        # Embat is settling 100% of the booked accounting amount of a foreign-currency invoice
                        # (sending any FX gain/loss as a separate accounting payment), so match exact foreign residual
                        op_foreign_raw = sum(rec_lines.mapped("amount_residual_currency"))
                    else:
                        op_foreign_raw = None
                else:
                    op_raw = (
                        op.get("paymentAmount")
                        if op.get("paymentAmount") not in (None, 0, 0.0)
                        else (
                            op.get("operationPaymentAmount")
                            if op.get("operationPaymentAmount") not in (None, 0, 0.0)
                            else op.get("amount")
                        )
                    )
                    if op_raw not in (None, 0, 0.0):
                        if idx == len(valid_ops) - 1 and total_signed_company_amt:
                            op_company_signed = company.currency_id.round(
                                total_signed_company_amt - allocated_so_far
                            )
                        else:
                            op_company_signed = company.currency_id.round(
                                float(op_raw) * conv_ratio
                            )
                        if (
                            op.get("currency") == inv_currency.name
                            and op.get("amount") not in (None, 0, 0.0)
                        ):
                            op_foreign_raw = float(op["amount"])
                        elif pay_currency and pay_currency == inv_currency:
                            op_foreign_raw = float(op_raw)
                        elif (
                            inv_currency != company.currency_id
                            and company.currency_id.compare_amounts(
                                op_company_signed, sum(rec_lines.mapped("amount_residual"))
                            )
                            == 0
                        ):
                            op_foreign_raw = sum(rec_lines.mapped("amount_residual_currency"))
                        else:
                            op_foreign_raw = None
                    else:
                        # Fallback to invoice open residual
                        if idx == len(valid_ops) - 1 and total_signed_company_amt:
                            op_company_signed = company.currency_id.round(
                                total_signed_company_amt - allocated_so_far
                            )
                        else:
                            op_company_signed = sum(rec_lines.mapped("amount_residual"))
                        op_foreign_raw = (
                            sum(rec_lines.mapped("amount_residual_currency"))
                            if inv_currency != company.currency_id
                            and company.currency_id.compare_amounts(
                                op_company_signed, sum(rec_lines.mapped("amount_residual"))
                            )
                            == 0
                            else None
                        )
                    allocated_so_far += op_company_signed

                amounts = self._compute_embat_counterpart_amounts(
                    op_company_signed,
                    company,
                    date,
                    raw_foreign_amount=op_foreign_raw,
                    target_currency=inv_currency,
                )
                partner_id = rec_lines[0].partner_id.id or move.partner_id.id or False
                new_lines_spec.append(
                    {
                        "account_id": target_account.id,
                        "partner_id": partner_id,
                        "name": concept or test_st_line_1.payment_ref or move.name,
                        "debit": amounts["debit"],
                        "credit": amounts["credit"],
                        "currency_id": amounts["currency_id"],
                        "amount_currency": amounts["amount_currency"],
                        "analytic_distribution": analytic_distribution,
                        "reconcile_lines": rec_lines,
                    }
                )

            self._apply_embat_lines_to_statement_line(
                test_st_line_1,
                journal,
                company,
                new_lines_spec,
                concept=concept,
                transaction_id=transaction_id,
                error_context_id=payment.get("id"),
            )
            _logger.info(
                "Successfully reconciled statement line %s with %s operation(s)",
                test_st_line_1.id,
                len(new_lines_spec),
            )

        _logger.info("=============================================")
        sync_id = payment.get("customId") or payment.get("id")
        _logger.info("CustomId: %s", sync_id)
        if sync_id:
            self.mark_as_sync(sync_id)

    def get_payment_accounting(self, payment, company):
        _logger.info("DEBUG EMBAT PAYMENT ACCOUNTING: %s", payment)
        account_debit_id = self.env["account.account"].search(
            [("code", "=", payment["accountingCode"]), ("company_id", "=", company.id)],
            limit=1,
        )
        if not account_debit_id:
            account_debit_id = self.default_payment_account
        if not account_debit_id:
            message = _("Account not found for Embat accountingCode: %s") % payment.get(
                "accountingCode"
            )
            company.sudo().message_post(body=message)
            return

        journal = self.env["account.journal"].search(
            [
                ("embat_id", "=", payment["productId"]),
                ("type", "=", "bank"),
                ("company_id", "=", company.id),
            ],
            limit=1,
        )
        if not journal:
            message = _("Journal not found for Embat ProudctId: %s" % payment["productId"])
            company.sudo().message_post(body=message)
            return

        date = fields.Date.today()
        if "date" in payment and payment["date"]:
            date = payment["date"].split("T")[0]

        analytic_distribution = self._parse_analytic_distribution(payment, company)
        transaction_id = payment.get("transactionId")

        st_line = self._find_embat_statement_line(payment, journal, company, date)
        if not st_line:
            _logger.warning("Statement line not found for payment %s", payment.get("id"))
            message = _("Statement line not found for payment %s") % payment.get("id")
            company.sudo().message_post(body=message)
            return
        _logger.info("Found st_line %s", st_line.id)

        signed_company_amt = self._get_signed_payment_company_amount(payment)
        if not signed_company_amt:
            return

        pay_currency_code = payment.get("currency")
        pay_currency = (
            self.env["res.currency"].search([("name", "=", pay_currency_code)], limit=1)
            if pay_currency_code
            else False
        )
        amounts = self._compute_embat_counterpart_amounts(
            signed_company_amt,
            company,
            date,
            raw_foreign_amount=payment.get("amount"),
            target_currency=pay_currency or company.currency_id,
        )

        partner = self._resolve_embat_partner(payment)
        partner_id = partner.id if partner else (st_line.partner_id.id or False)
        concept = payment.get("concept")

        new_lines_spec = [
            {
                "account_id": account_debit_id.id,
                "partner_id": partner_id,
                "name": concept or st_line.payment_ref or account_debit_id.name,
                "debit": amounts["debit"],
                "credit": amounts["credit"],
                "currency_id": amounts["currency_id"],
                "amount_currency": amounts["amount_currency"],
                "analytic_distribution": analytic_distribution,
                "reconcile_lines": False,
            }
        ]

        self._apply_embat_lines_to_statement_line(
            st_line,
            journal,
            company,
            new_lines_spec,
            concept=concept,
            transaction_id=transaction_id,
            error_context_id=payment.get("id"),
        )

        sync_id = payment.get("customId") or payment.get("id")
        if sync_id:
            self.mark_as_sync(sync_id)

    def get_payment_contacts(self, payment, company):
        _logger.info("DEBUG EMBAT PAYMENT CONTACTS: %s", payment)

        analytic_distribution = self._parse_analytic_distribution(payment, company)
        partner = self._resolve_embat_partner(payment)

        if not partner:
            message = _("Contact not found for Embat payment: %s") % payment.get("id")
            company.sudo().message_post(body=message)
            return

        journal = self.env["account.journal"].search(
            [
                ("embat_id", "=", payment["productId"]),
                ("type", "=", "bank"),
                ("company_id", "=", company.id),
            ],
            limit=1,
        )
        if not journal:
            message = _("Journal not found for Embat ProductId: %s") % payment["productId"]
            company.sudo().message_post(body=message)
            return

        date = fields.Date.today()
        if "date" in payment and payment["date"]:
            date = payment["date"].split("T")[0]

        signed_company_amt = self._get_signed_payment_company_amount(payment)
        if not signed_company_amt:
            return

        partner_company = partner.with_company(company)
        payment_type = "inbound" if signed_company_amt > 0 else "outbound"
        destination_account = (
            partner_company.property_account_receivable_id
            if payment_type == "inbound"
            else partner_company.property_account_payable_id
        )

        transaction_id = payment.get("transactionId")
        test_st_line_1 = self._find_embat_statement_line(payment, journal, company, date)

        if not test_st_line_1:
            _logger.warning("Statement line not found for contact payment %s", payment.get("id"))
            message = _("Statement line not found for contact payment %s") % payment.get("id")
            company.sudo().message_post(body=message)
            return
        _logger.info("Found st_line %s", test_st_line_1.id)

        pay_currency_code = payment.get("currency")
        pay_currency = (
            self.env["res.currency"].search([("name", "=", pay_currency_code)], limit=1)
            if pay_currency_code
            else False
        )
        amounts = self._compute_embat_counterpart_amounts(
            signed_company_amt,
            company,
            date,
            raw_foreign_amount=payment.get("amount"),
            target_currency=pay_currency or company.currency_id,
        )
        concept = payment.get("concept")

        new_lines_spec = [
            {
                "account_id": destination_account.id,
                "partner_id": partner.id,
                "name": concept or test_st_line_1.payment_ref or partner.name,
                "debit": amounts["debit"],
                "credit": amounts["credit"],
                "currency_id": amounts["currency_id"],
                "amount_currency": amounts["amount_currency"],
                "analytic_distribution": analytic_distribution,
                "reconcile_lines": False,
            }
        ]

        self._apply_embat_lines_to_statement_line(
            test_st_line_1,
            journal,
            company,
            new_lines_spec,
            concept=concept,
            transaction_id=transaction_id,
            error_context_id=payment.get("id"),
        )

        sync_id = payment.get("customId") or payment.get("id")
        if sync_id:
            self.mark_as_sync(sync_id)

    def mark_as_sync(self, customid, endpoint_type="payments"):
        endpoint = f"{endpoint_type}/" + self.embat_company_id + "/" + customid
        _logger.info("Endpoint: %s", endpoint)
        request_type = "patch"
        data = {"sync": "true"}
        _logger.info("Data: %s", data)
        try:
            if "fallback_on_404" in inspect.signature(self._embat_request).parameters:
                response, content = self._embat_request(
                    endpoint, self, request_type=request_type, data=data, fallback_on_404=False
                )
            else:
                response, content = self._embat_request(
                    endpoint, self, request_type=request_type, data=data
                )
            _logger.info("Response: %s", response)
            _logger.info("Content: %s", content)
        except Exception as e:
            _logger.warning(
                "Failed to mark payment %s as synced on Embat (it may have been deleted). Error: %s",
                customid,
                str(e),
            )

    def reconciliate_payment_embat(self, payment, move, journal, company, date):
        lines_to_reconcile = self.env["account.move.line"]
        payment_lines = payment.move_id.line_ids.filtered(
            lambda l: l.account_id.account_type in ("asset_receivable", "liability_payable")
        )
        move_lines = move.line_ids.filtered(
            lambda l: l.account_id.account_type in ("asset_receivable", "liability_payable")
        )
        lines_to_reconcile += payment_lines
        lines_to_reconcile += move_lines
        try:
            lines_to_reconcile.reconcile()
        except Exception as e:
            message = _("Error reconciling payment %s with invoice %s: %s") % (
                payment.name,
                move.name,
                str(e),
            )
            _logger.error(message)

    def reconcile_payment(
        self, payment, move, journal, company, date=fields.Date.today(), transaction_id=False
    ):
        try:
            sign = -1
            if move.move_type in ["out_invoice", "in_refund", "out_receipt"]:
                sign = 1

            company_id = company.id if isinstance(company, models.Model) else company

            test_st_line_1 = False
            _logger.info(
                "Searching st_line by unique_import_id ilike %s for company %s",
                transaction_id,
                company_id,
            )
            if transaction_id:
                test_st_line_1 = self.env["account.bank.statement.line"].search(
                    [("unique_import_id", "ilike", transaction_id), ("company_id", "=", company_id)],
                    limit=1,
                )

            if not test_st_line_1:
                st_line_amount = payment.amount * sign
                domain_fallback = [
                    ("amount", "=", st_line_amount),
                    ("date", "=", date),
                    ("journal_id", "=", journal.id),
                    ("company_id", "=", company_id),
                    ("is_reconciled", "=", False),
                ]
                _logger.info("Fallback search domain: %s", domain_fallback)
                st_lines = self.env["account.bank.statement.line"].search(domain_fallback)
                _logger.info("Fallback search found %s lines", len(st_lines))
                if len(st_lines) == 1:
                    test_st_line_1 = st_lines[0]
                elif len(st_lines) > 1:
                    st_lines_concept = st_lines.filtered(lambda l: l.payment_ref == payment.name)
                    _logger.info(
                        "Filtered by concept %s found %s lines",
                        payment.name,
                        len(st_lines_concept),
                    )
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
                counterpart_line = payment.move_id.line_ids.filtered(
                    lambda line: line.account_id.account_type
                    not in ("asset_receivable", "liability_payable")
                    and not line.reconciled
                )
                if len(counterpart_line) > 1:
                    counterpart_line = (
                        counterpart_line.filtered(
                            lambda l: l.account_id.account_type in ("asset_cash", "asset_current")
                        )
                        or counterpart_line[0]
                    )
                if counterpart_line:
                    counterpart_line = counterpart_line[0]
                    company_rec = (
                        company
                        if isinstance(company, models.Model)
                        else self.env["res.company"].browse(company_id)
                    )
                    if not counterpart_line.account_id.reconcile:
                        if counterpart_line.move_id.state == "posted":
                            counterpart_line.move_id.button_draft()
                        fallback_acc = (
                            journal.suspense_account_id or counterpart_line.account_id
                        )
                        counterpart_line.with_context(check_move_validity=False).write(
                            {"account_id": fallback_acc.id}
                        )
                        if counterpart_line.move_id.state == "draft":
                            counterpart_line.move_id.action_post()

                    signed_amt = payment.amount * sign
                    amounts = self._compute_embat_counterpart_amounts(
                        signed_amt, company_rec, date
                    )
                    self._apply_embat_lines_to_statement_line(
                        test_st_line_1,
                        journal,
                        company_rec,
                        [
                            {
                                "account_id": counterpart_line.account_id.id,
                                "partner_id": payment.partner_id.id,
                                "name": payment.name,
                                "debit": amounts["debit"],
                                "credit": amounts["credit"],
                                "currency_id": amounts["currency_id"],
                                "amount_currency": amounts["amount_currency"],
                                "analytic_distribution": {},
                                "reconcile_lines": counterpart_line,
                            }
                        ],
                        concept=payment.name,
                        transaction_id=transaction_id,
                    )
        except Exception as e:
            message = _("Cannot update EMBAT Payment because: %s" % (e))
            self.sudo().message_post(body=message)
            raise e
