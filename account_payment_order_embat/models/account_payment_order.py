# Copyright 2025 Acysos S.L. (https://www.acysos.com)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import models


class AccountPaymentOrder(models.Model):
    _inherit = "account.payment.order"

    def generated2uploaded(self):
        res = super().generated2uploaded()
        for order in self:
            if order.company_id.use_embat:
                for payment in order.payment_ids:
                    payment.send_payment_to_embat()
        return res

