# Copyright 2025 Acysos S.L. (https://www.acysos.com)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
import datetime


EMBAT_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"


class AccountMove(models.Model):
    _inherit = "account.move"
    
    embat_id = fields.Char(
        string="Embat ID",
        help="The ID of the move in Embat.",
        readonly=True,
        copy=False,
    )

    embat_api_log_ids = fields.Many2many(
        comodel_name="embat.api.log",
        compute="_compute_embat_api_log_ids",
        string="Embat API Logs",
    )

    def _compute_embat_api_log_ids(self):
        for record in self:
            domain = [
                ("model", "=", record._name),
                ("res_id", "=", record.id),
            ]
            record.embat_api_log_ids = self.env["embat.api.log"].search(domain)

    def _prepare_embat_move_data(self, status, embat_type):
        self.ensure_one()
        attributes = []
        analytic_account_ids = set()
        for line in self.line_ids:
            if line.analytic_account_id:
                analytic_account_ids.add(line.analytic_account_id.id)
        
        if analytic_account_ids:
            accounts = self.env['account.analytic.account'].browse(list(analytic_account_ids))
            for account in accounts:
                attributes.append({
                    "customId": str(account.id),
                    "value": account.name,
                    "valueCustomId": str(account.id),
                })

        sign = 1 if self.move_type in ['out_invoice', 'in_refund', 'out_receipt'] else -1 if self.move_type in ['in_invoice', 'out_refund', 'in_receipt'] else 1
        amount_total_in_currency_signed = abs(self.amount_total) if self.move_type == 'entry' else self.amount_total * sign

        return {
            "status": status,
            "chargeAccount": None,
            "contactAccount": None,
            "issuanceDate": str(self.invoice_date) + 'T12:00:00.000Z' if self.invoice_date else str(fields.Date.context_today(self)) + 'T12:00:00.000Z',
            "dueDate": str(self.invoice_date_due) + 'T12:00:00.000Z' if self.invoice_date_due else '2999-12-31T12:00:00.000Z',
            "concept": self.ref if self.ref else '' + (self.name if self.name else ''),
            "amount": amount_total_in_currency_signed,
            "currency": self.currency_id.name if self.currency_id else self.company_id.currency_id.name,
            "accountingAmount": self.amount_total_signed,
            "accountingCurrency": self.company_id.currency_id.name if self.company_id.currency_id else 'EUR',
            "exchangeRate": self.currency_id.rate if self.currency_id and self.company_id.currency_id and self.currency_id != self.company_id.currency_id else 1.0,
            "sync": False,
            "attributes": attributes if attributes else None,
            "contact": {
                "tradeName": str(self.partner_id.name),
                "legalName": str(self.partner_id.name),
                "type": embat_type,
                "customId": str(self.partner_id.id)
            },
            "customId": str(self._name) + "-" + str(self.id),
            "documentId": self.ref if self.ref else '' + (self.name if self.name else ''),
            "documentType": "invoice",
            "tags": None,
            "pendingAmount": self.amount_residual_signed,
            "pendingAccountingAmount": self.amount_residual_signed,
            "comments": None,
            "uploadedFiles": None,
            "secondary": None
        }

    def _load_embat_move_operation(self):
        if self.env.company.use_embat:
            for move in self:
                embat_data = move.env.company.embat_data_id
                if not embat_data:
                    raise UserError(_("Please configure the Embat data first."))
                date_value = move.date or fields.Date.context_today(move)
                if isinstance(date_value, str):
                    date_obj = fields.Date.from_string(date_value)
                else:
                    date_obj = date_value
                embat_format_date = date_obj.strftime(EMBAT_DATE_FORMAT)

                status = "pending"
                if move.state == "draft":
                    status = "shipped"
                if move.state == "posted":
                    status = "pending"
                    if move.invoice_date_due and move.invoice_date_due > fields.Datetime.now().date():
                        status = "overdue"

                    if move.payment_state == "paid":
                        status = "paid"
                    elif move.payment_state == "in_payment":
                        status = "payment_in_progress"
                if move.state == "cancel":
                    status = "cancel"
                embat_type = "client-supplier"
                if move.partner_id.customer_rank == 0:
                    embat_type = "supplier"
                if move.partner_id.supplier_rank == 0:
                    embat_type = "client"
                # if move.move_type in ['out_invoice', 'in_refund', 'out_receipt']:
                #     sign = 1
                # else:
                #     sign = -1
                #
                # amount_total = move.amount_total * sign
                # amount_residual = move.amount_residual * sign

                data = move._prepare_embat_move_data(status, embat_type)
                if move.embat_id:
                    endpoint = "operations/" + embat_data.embat_company_id + "/" + str(move._name) + "-" + str(move.id)
                    request_type = "patch"
                else:
                    endpoint = "operations/" + embat_data.embat_company_id
                    request_type = "post"
                response, content = embat_data._embat_request(endpoint, move, request_type=request_type, data=data)
                if not content or "id" not in content:
                    message = _("Could not retrieve the move line ID from Embat: %s") % (response)
                    embat_data._create_log("ERROR", "OPERATIONS_ERROR", message, move)
                    raise ValidationError(message)
                move.embat_id = content["id"]
                message = _("Move line synced with Embat successfully: %s") % (move.embat_id)
                embat_data._create_log("INFO", "OPERATIONS_INFO", message, move)
                
    def _delete_embat_move_line_operation(self):
        """Delete the Embat move line if it exists."""
        for move in self:
            if move.embat_id:
                embat_data = move.env.company.embat_data_id
                if not embat_data:
                    raise UserError(_("Please configure the Embat data first."))
                endpoint = "operations/" + embat_data.embat_company_id + "/" + str(move._name) + "-" + str(move.id)
                response, content = embat_data._embat_request(endpoint, move, request_type="delete")
                if response.status_code != 200:
                    message = _("Could not delete the move line in Embat: %s") % (response)
                    embat_data._create_log("ERROR", "OPERATIONS_ERROR", message, move)
                    raise ValidationError(message)
                message = _("Move line deleted in Embat successfully: %s") % (move.embat_id)
                embat_data._create_log("INFO", "OPERATIONS_INFO", message, move)
                move.embat_id = False

    def action_post(self):
        res = super(AccountMove, self).action_post()
        if self.env.company.use_embat:
            for move in self:
                if move.journal_id and move.journal_id.embat_id and move.move_type in ['out_invoice', 'in_refund', 'out_receipt', 'in_invoice', 'in_receipt', 'out_refund']:
                    move._load_embat_move_operation()
                for line in move.line_ids:
                    if line.journal_id and line.journal_id.embat_id and line.account_id.user_type_id.type in ['liquidity']:
                        line._load_embat_move_line_asset()
        return res
