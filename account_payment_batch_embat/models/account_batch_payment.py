# Copyright 2025 Acysos S.L. (https://www.acysos.com)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import models


class AccountBatchPayment(models.Model):
    _inherit = "account.batch.payment"

    def _send_after_validation(self):
        res = super()._send_after_validation()
        for batch in self:
            if batch.journal_id.company_id.use_embat:
                for payment in batch.payment_ids:
                    payment.send_payment_to_embat()
        return res
