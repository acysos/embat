# Copyright 2025 Acysos S.L. (https://www.acysos.com)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import models, fields


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    def _prepare_embat_move_line_data(self, embat_format_date):
        data = super()._prepare_embat_move_line_data(embat_format_date)
        data['transactionIds'] = (
            self.move_id.embat_transaction_id.split(",")
            if self.move_id.embat_transaction_id else [])
        return data
