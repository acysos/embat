# Copyright 2025 Acysos S.L. (https://www.acysos.com)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models, api


class EmbatLogDisplayMixin(models.AbstractModel):
    _name = "embat.log.display.mixin"
    _description = "Mixin to display Embat API Logs"

    embat_api_log_ids = fields.Many2many(
        comodel_name="embat.api.log",
        string="Embat API Logs",
        compute="_compute_embat_api_log_ids",
        readonly=True,
    )

    def _compute_embat_api_log_ids(self):
        for record in self:
            if not isinstance(record.id, models.NewId):
                record.embat_api_log_ids = self.env["embat.api.log"].search([
                    ("model", "=", record._name),
                    ("res_id", "=", record.id),
                ])
            else:
                record.embat_api_log_ids = False






