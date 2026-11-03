# Copyright 2025 Acysos S.L. (https://www.acysos.com)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import _, api, fields, models
from odoo.exceptions import UserError



class AccountPayment(models.Model):
    _inherit = 'account.payment'

    embat_id = fields.Char(string='Embat ID', copy=False)
    embat_transaction_id = fields.Char(
        string='Embat Transaction ID', copy=False)
    
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
            record.embat_api_log_ids = self.env["embat.api.log"].sudo().search(domain)

    @api.model_create_multi
    def create(self, vals_list):
        payments = super().create(vals_list)
        for payment in payments:
            if payment.embat_transaction_id and payment.move_id:
                payment.move_id.embat_transaction_id = (
                    payment.embat_transaction_id)
        return payments

    def write(self, vals):
        res = super().write(vals)
        if 'embat_transaction_id' in vals:
            for payment in self:
                if payment.move_id:
                    payment.move_id.embat_transaction_id = (
                        payment.embat_transaction_id)
        return res

    # def _prepare_embat_payment_data(self):
    #     self.ensure_one()
    #     return {
    #         "amount": self.amount,
    #         "currency": self.currency_id.name,
    #         "date": str(self.date) + 'T12:00:00.000Z',
    #         "concept": self.memo or self.name,
    #         "customId": f"{self._name}-{self.id}",
    #         "contact": {
    #             "legalName": self.partner_id.name,
    #             "customId": str(self.partner_id.id),
    #         } if self.partner_id else None,
    #     }

    def _prepare_embat_payment_data(self):
        self.ensure_one()
        sign = -1 if self.payment_type == "outbound" else 1
        signed_amount = self.amount * sign
        operations = []
        if hasattr(self, 'payment_line_ids') and self.payment_line_ids:
            for payment_line in self.payment_line_ids:
                if payment_line.move_line_id and payment_line.move_line_id.move_id:
                    line_amount = (
                        getattr(payment_line, "amount_currency", 0.0)
                        or getattr(payment_line, "amount", 0.0)
                        or self.amount
                    )
                    operations.append(
                        {
                            "amount": abs(line_amount) * sign,
                            "customId": f"account.move-{payment_line.move_line_id.move_id.id}",
                        }
                    )
        else:
            invoices = self.reconciled_invoice_ids | self.reconciled_bill_ids
            for invoice in invoices:
                inv_amount = (
                    abs(invoice.amount_total_in_currency_signed) * sign
                    if len(invoices) > 1
                    else signed_amount
                )
                operations.append(
                    {
                        "amount": inv_amount,
                        "customId": f"account.move-{invoice.id}",
                    }
                )
        payment_data = {
            "operations": operations,
            "amount": signed_amount,
            "accountingAmount": signed_amount,
            "currency": self.currency_id.name,
            "date": str(self.date) + 'T12:00:00.000Z',
            "concept": self.memo or self.name,
            "type": "operations",
            "contactCustomId": str(self.partner_id.id) if self.partner_id else None,
            "contactCompanyId": self.partner_id.id if self.partner_id else None,
            "customId": f"{self._name}-{self.id}",
        }
        return payment_data

    def _prepare_embat_operation_data(self, move):
        self.ensure_one()
        return {
            "invoiceGroupDocumentId": self.name,
            "customId": f"account.move-{move.id}",
        }

    def send_payment_to_embat(self):
        """Send payment to Embat."""
        self.ensure_one()
        company = self.company_id or self.env.company
        if not company.use_embat:
            return
        
        embat_data = company.embat_data_id
        if not embat_data:
            raise UserError(_("Please configure the Embat data first."))
            
        data = self._prepare_embat_payment_data()
        endpoint = f"payments/{embat_data.embat_company_id}"
        
        request_type = "post"
        if self.embat_id:
            endpoint = f"payments/{embat_data.embat_company_id}/{self.embat_id}"
            request_type = "patch"
            
        try:
            response, content = embat_data._embat_request(
                endpoint, self, request_type=request_type, data=data
            )
            
            if response.ok:
                if content and "id" in content:
                    self.embat_id = content["id"]
                    msg = _("Payment synced with Embat: %s") % self.embat_id
                    embat_data._create_log("INFO", "PAYMENTS_INFO", msg, self)
                    
                    # Fetch transactionID
                    try:
                        get_endpoint = f"payments/{embat_data.embat_company_id}/{self.embat_id}"
                        get_response, get_content = embat_data._embat_request(
                            get_endpoint, self, request_type="get"
                        )
                        if get_response.ok and isinstance(get_content, dict):
                            payload = (
                                get_content["data"]
                                if isinstance(get_content.get("data"), dict)
                                else get_content
                            )
                            transaction_id = payload.get("transactionId")
                            if transaction_id:
                                self.embat_transaction_id = transaction_id
                                msg = _("Transaction ID retrieved from Embat: %s") % transaction_id
                                embat_data._create_log("INFO", "PAYMENTS_INFO", msg, self)
                    except Exception as e:
                        msg = _("Failed to retrieve transaction ID from Embat: %s") % str(e)
                        embat_data._create_log("WARNING", "PAYMENTS_WARNING", msg, self)

                elif request_type == "post":
                    msg = _("Payment sent to Embat but no ID returned.")
                    embat_data._create_log("WARNING", "PAYMENTS_WARNING", msg, self)

                moves_to_update = self.env["account.move"]
                if hasattr(self, "payment_line_ids") and self.payment_line_ids:
                    moves_to_update = self.payment_line_ids.mapped("move_line_id.move_id")
                else:
                    moves_to_update = self.reconciled_invoice_ids | self.reconciled_bill_ids

                for move in moves_to_update:
                    if not move.embat_id:
                        continue
                    endpoint = f"operations/{embat_data.embat_company_id}/account.move-{move.id}"
                    request_type = "patch"
                    move_data = self._prepare_embat_operation_data(move)
                    try:
                        response, content = embat_data._embat_request(
                            endpoint,
                            self,
                            request_type=request_type,
                            data=move_data,
                            fallback_on_404=False,
                        )
                        if response.ok:
                            msg = _("Operation invoiceGroupDocumentId %s with Embat: %s") % (move_data['invoiceGroupDocumentId'], move.embat_id)
                            embat_data._create_log("INFO", "OPERATIONS_INFO", msg, self)
                    except Exception as e:
                        msg = _("Failed to sync operation invoiceGroupDocumentId %s with Embat: %s") % (move_data['invoiceGroupDocumentId'], move.embat_id)
                        embat_data._create_log("ERROR", "OPERATIONS_ERROR", msg, self)
                    
                    
        except Exception as e:
            msg = _("Failed to sync payment with Embat: %s") % str(e)
            embat_data._create_log("ERROR", "PAYMENTS_ERROR", msg, self)
            # We do NOT raise here to avoid blocking the whole batch if one fails?
            # Or should we? User said "communicate", usually implies we want it to work.
            # But blocking a batch validation might be annoying. 
            # I will log and pass for now unless crucial.

