# Copyright 2025 Acysos S.L.
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import models, fields, api, _


class EmbatCompanyWizard(models.TransientModel):
    _name = 'embat.company.wizard'
    _description = 'Wizard to select an Embat company'

    name = fields.Char(string="Name")
    embat_id = fields.Char(string="ID Embat", required=True)
    embat_data_id = fields.Many2one('embat.data', string="Embat Data")

    def action_select_company(self):
        self.embat_data_id.embat_company_id = self.embat_id
