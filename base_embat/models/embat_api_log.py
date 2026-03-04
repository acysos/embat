# Copyright 2025 Acysos S.L. (https://www.acysos.com)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class EmbatApiLog(models.Model):
    _name = "embat.api.log"
    _description = "Embat API Log"
    _order = "create_date desc"

    name = fields.Char(string="Endpoint", required=True)
    model = fields.Char(string="Model")
    res_id = fields.Integer(string="Resource ID")
    request_type = fields.Selection(
        selection=[
            ("get", "GET"),
            ("post", "POST"),
            ("put", "PUT"),
            ("patch", "PATCH"),
            ("delete", "DELETE"),
        ],
        string="Request Type",
        required=True,
    )
    params = fields.Text(string="Params")
    headers = fields.Text(string="Headers")
    data = fields.Text(string="Data (JSON)")
    response = fields.Text(string="Response")
