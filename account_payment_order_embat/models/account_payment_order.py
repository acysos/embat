# Copyright 2025 Acysos S.L. (https://www.acysos.com)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import models


class AccountPaymentOrder(models.Model):
    _inherit = "account.payment.order"

    def post_and_reconcile(self):
        self.payment_ids.action_post()
        for order in self:
            if order.company_id.use_embat:
                for payment in order.payment_ids:
                    payment.with_company(order.company_id).send_payment_to_embat()
        for payment in self.payment_ids:
            (
                payment.payment_line_ids.move_line_id
                + payment.move_id.line_ids.filtered(
                    lambda x, p=payment: x.account_id == p.destination_account_id
                )
            ).reconcile()

    def generated2uploaded(self):
        res = super().generated2uploaded()
        for order in self:
            if order.company_id.use_embat:
                for payment in order.payment_ids.filtered(lambda p: not p.embat_id):
                    payment.with_company(order.company_id).send_payment_to_embat()
        return res

