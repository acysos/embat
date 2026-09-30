# Copyright 2025 Acysos S.L. (https://www.acysos.com)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)



class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    def reconcile(self):
        res = super().reconcile()
        moves = self.mapped('move_id')
        for move in moves:
            if move.env.company.use_embat and move.embat_id and move.move_type in ['out_invoice', 'in_refund', 'out_receipt', 'in_invoice', 'in_receipt', 'out_refund']:
                transaction_ids = set()
                if move.embat_transaction_id:
                    for t in move.embat_transaction_id.split(','):
                        if t.strip():
                            transaction_ids.add(t.strip())
                for line in move.line_ids.filtered(lambda l: l.account_id.account_type in ('asset_receivable', 'liability_payable')):
                    matched_lines = line.matched_debit_ids.debit_move_id + line.matched_credit_ids.credit_move_id
                    for m_line in matched_lines:
                        t_id = m_line.move_id.embat_transaction_id
                        if not t_id and m_line.payment_id:
                            t_id = m_line.payment_id.embat_transaction_id
                        if not t_id and m_line.statement_line_id and m_line.statement_line_id.unique_import_id:
                            t_id = m_line.statement_line_id.unique_import_id
                        if t_id:
                            for t in t_id.split(','):
                                if t.strip():
                                    transaction_ids.add(t.strip())
                if transaction_ids:
                    move.embat_transaction_id = ",".join(list(transaction_ids))
                if hasattr(move.env, 'flush_all'):
                    move.env.flush_all()
                else:
                    move.flush()
                
                if hasattr(move, 'invalidate_recordset'):
                    move.invalidate_recordset(['payment_state', 'amount_residual'])
                
                if hasattr(move, '_compute_amount'):
                    move._compute_amount()
                
                move._load_embat_move_operation()
        return res

    def remove_move_reconcile(self):
        moves = self.mapped('move_id')
        res = super().remove_move_reconcile()
        for move in moves:
            if move.env.company.use_embat and move.embat_id and move.move_type in ['out_invoice', 'in_refund', 'out_receipt', 'in_invoice', 'in_receipt', 'out_refund']:
                if hasattr(move.env, 'flush_all'):
                    move.env.flush_all()
                else:
                    move.flush()
                
                if hasattr(move, 'invalidate_recordset'):
                    move.invalidate_recordset(['payment_state', 'amount_residual'])
                
                if hasattr(move, '_compute_amount'):
                    move._compute_amount()
                
                move._load_embat_move_operation()
        return res

class AccountPartialReconcile(models.Model):
    _inherit = "account.partial.reconcile"

    @api.model_create_multi
    def create(self, vals_list):
        res = super().create(vals_list)
        moves = self.env['account.move']
        for partial in res:
            moves |= partial.debit_move_id.move_id
            moves |= partial.credit_move_id.move_id
        
        for move in moves:
            if move.env.company.use_embat and move.embat_id and move.move_type in ['out_invoice', 'in_refund', 'out_receipt', 'in_invoice', 'in_receipt', 'out_refund']:
                transaction_ids = set()
                if move.embat_transaction_id:
                    for t in move.embat_transaction_id.split(','):
                        if t.strip():
                            transaction_ids.add(t.strip())
                for line in move.line_ids.filtered(lambda l: l.account_id.account_type in ('asset_receivable', 'liability_payable')):
                    matched_lines = line.matched_debit_ids.debit_move_id + line.matched_credit_ids.credit_move_id
                    for m_line in matched_lines:
                        t_id = m_line.move_id.embat_transaction_id
                        if not t_id and m_line.payment_id:
                            t_id = m_line.payment_id.embat_transaction_id
                        if not t_id and m_line.statement_line_id and m_line.statement_line_id.unique_import_id:
                            t_id = m_line.statement_line_id.unique_import_id
                        if t_id:
                            for t in t_id.split(','):
                                if t.strip():
                                    transaction_ids.add(t.strip())
                if transaction_ids:
                    move.embat_transaction_id = ",".join(list(transaction_ids))
                
                if hasattr(move.env, 'flush_all'):
                    move.env.flush_all()
                else:
                    move.flush()
                
                if hasattr(move, 'invalidate_recordset'):
                    move.invalidate_recordset(['payment_state', 'amount_residual'])
                
                if hasattr(move, '_compute_amount'):
                    move._compute_amount()
                    
                if hasattr(move.env, 'flush_all'):
                    
                    move.env.flush_all()
                    
                else:
                    
                    move.flush()
                    
                
                    
                if hasattr(move, 'invalidate_recordset'):
                    
                    move.invalidate_recordset(['payment_state', 'amount_residual'])
                    
                
                    
                if hasattr(move, '_compute_amount'):
                    
                    move._compute_amount()
                    
                
                    
                move._load_embat_move_operation()
        return res

    def unlink(self):
        moves = self.env['account.move']
        for partial in self:
            moves |= partial.debit_move_id.move_id
            moves |= partial.credit_move_id.move_id
        
        res = super().unlink()
        
        for move in moves:
            if move.env.company.use_embat and move.embat_id and move.move_type in ['out_invoice', 'in_refund', 'out_receipt', 'in_invoice', 'in_receipt', 'out_refund']:
                if hasattr(move.env, 'flush_all'):
                    move.env.flush_all()
                else:
                    move.flush()
                if hasattr(move, 'invalidate_recordset'):
                    move.invalidate_recordset(['payment_state', 'amount_residual'])
                if hasattr(move, '_compute_amount'):
                    move._compute_amount()
                if hasattr(move.env, 'flush_all'):
                    move.env.flush_all()
                else:
                    move.flush()
                
                if hasattr(move, 'invalidate_recordset'):
                    move.invalidate_recordset(['payment_state', 'amount_residual'])
                
                if hasattr(move, '_compute_amount'):
                    move._compute_amount()
                
                move._load_embat_move_operation()
        return res
