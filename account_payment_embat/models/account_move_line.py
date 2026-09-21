# Copyright 2025 Acysos S.L. (https://www.acysos.com)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import models, fields


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    def reconcile(self):
        res = super().reconcile()
        moves = self.mapped('move_id')
        for move in moves:
            if move.env.company.use_embat and move.embat_id and move.move_type in ['out_invoice', 'in_refund', 'out_receipt', 'in_invoice', 'in_receipt', 'out_refund']:
                move._load_embat_move_operation()
        return res

    def remove_move_reconcile(self):
        moves = self.mapped('move_id')
        res = super().remove_move_reconcile()
        for move in moves:
            if move.env.company.use_embat and move.embat_id and move.move_type in ['out_invoice', 'in_refund', 'out_receipt', 'in_invoice', 'in_receipt', 'out_refund']:
                move._load_embat_move_operation()
        return res
