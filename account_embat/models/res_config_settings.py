# Copyright 2025 Acysos S.L. (https://www.acysos.com)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    use_embat = fields.Boolean(
        string="Use Embat",
        help="Enable the use of Embat for online bank statement import.",
        readonly=False, related='company_id.use_embat'
    )
    embat_data_id = fields.Many2one(
        comodel_name="embat.data",
        string="Embat Data",
        help="Data related to Embat integration.",
        readonly=False, related='company_id.embat_data_id'
    )

    def load_accounts(self):
        self.ensure_one()
        if not self.embat_data_id:
            raise UserError(_("Please configure the Embat data first."))
        account_ids = self.env['account.account'].search([('company_ids', 'in', self.env.company.id)])
        if not account_ids:
            raise UserError(_("No accounts found for the current company."))
        account_ids._load_embat_account()

    def load_analytic_accounts(self):
        self.ensure_one()
        if not self.embat_data_id:
            raise UserError(_("Please configure the Embat data first."))
        analytic_account_ids = self.env['account.analytic.account'].search(
            ['|', ('company_id', '=', self.env.company.id), ('company_id', '=', False)])
        if not analytic_account_ids:
            raise UserError(_("No analytic accounts found for the current company."))
        analytic_account_ids._load_embat_analytic_account()

    def load_pending_invoices(self):
        self.ensure_one()
        if not self.embat_data_id:
            raise UserError(_("Please configure the Embat data first."))
        move_ids = self.env['account.move'].search([
            ('company_id', '=', self.env.company.id),
            ('state', '=', 'posted'),
            ('payment_state', 'in', ['not_paid', 'partial']),
            ('move_type', 'in', ['out_invoice', 'in_refund', 'out_receipt', 'in_invoice', 'in_receipt', 'out_refund'])
        ])
        if not move_ids:
            raise UserError(_("No pending invoices found for the current company."))
        move_ids._load_embat_move_operation()

