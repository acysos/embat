# Copyright 2025 Acysos S.L.
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class EmbatAnalyticAccountMapping(models.Model):
    _name = "embat.analytic.account.mapping"
    _description = "Embat Analytic Account Mapping by Company"

    analytic_account_id = fields.Many2one(
        comodel_name="account.analytic.account",
        string="Analytic Account",
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
            "analytic_account_company_uniq",
            "unique(company_id, analytic_account_id)",
            "The mapping must be unique per company and analytic account!",
        )
    ]
