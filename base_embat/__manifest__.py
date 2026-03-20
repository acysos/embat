# Copyright 2025 Acysos S.L.
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    "name": "Base Embat",
    "version": "18.0.1.0.0",
    "category": "Account",
    "website": "https://github.com/OCA/server-tools",
    "author": "Acysos S.L., Odoo Community Association (OCA)",
    "license": "AGPL-3",
    "installable": True,
    "depends": [
        "base",
        "account",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/embat_data_view.xml",
        "wizards/embat_company_wizard_views.xml",
    ],
}
