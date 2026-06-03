# Copyright 2025 Acysos S.L. (https://www.acysos.com)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    "name": "Account: Embat",
    "version": "14.0.1.0.2",
    "category": "Account",
    "website": "https://github.com/OCA/account-financial-tools",
    "author": "Acysos S.L., Odoo Community Association (OCA)",
    "license": "AGPL-3",
    "installable": True,
    "depends": [
        "base_embat", "account",
    ],
    "data": [
        "views/res_config_settings_views.xml",
        "views/account_journal_views.xml",
        "views/account_move_views.xml",

    ],
}
