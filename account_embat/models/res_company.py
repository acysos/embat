# Copyright 2025 Acysos S.L. (https://www.acysos.com)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import _, api, fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    use_embat = fields.Boolean(
        string="Use Embat",
        help="Enable the use of Embat for online bank statement import.",
        default=False,
    )
    embat_data_id = fields.Many2one(
        comodel_name="embat.data",
        string="Embat Data",
        help="Data related to Embat integration.",
    )
