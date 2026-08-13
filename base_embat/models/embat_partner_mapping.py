# Copyright 2025 Acysos S.L.
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class EmbatPartnerMapping(models.Model):
    _name = "embat.partner.mapping"
    _description = "Embat Partner Mapping by Company"

    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Partner",
        required=True,
        ondelete="cascade",
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
        ondelete="cascade",
    )
    embat_id = fields.Char(
        string="Embat ID",
        required=True,
    )

    _sql_constraints = [
        (
            "embat_id_company_uniq",
            "unique(company_id, embat_id)",
            "The Embat ID must be unique per company!",
        )
    ]
