# Copyright 2025 Acysos S.L. (https://www.acysos.com)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import _, api, fields, models


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    embat_id = fields.Char(string='Embat ID', copy=False)
