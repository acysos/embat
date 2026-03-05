# Copyright 2025 Acysos S.L. (https://www.acysos.com)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class AccountMove(models.Model):
    _inherit = "account.move"

    embat_transaction_id = fields.Char(
        string="Embat Transaction ID",
        help="The ID of the transactions in Embat.",
        readonly=True,
    )