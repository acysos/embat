# Copyright 2025 Acysos S.L. (https://www.acysos.com)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import models, fields, api, _


class AccountMove(models.Model):
    _inherit = "account.move"

    embat_transaction_id = fields.Char(string='Embat Transaction ID', copy=False)

    def _prepare_embat_move_data(self, status, embat_type):
        data = super()._prepare_embat_move_data(status, embat_type)
        data['transactionIds'] = (
            self.embat_transaction_id.split(",")
            if self.embat_transaction_id else [])
        return data
