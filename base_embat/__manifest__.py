# Copyright 2025 Acysos S.L.
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    "name": "Base Embat",
    "version": "14.0.1.0.3",
    "category": "Account",
    "website": "https://github.com/OCA/server-tools",
    "author": "Acysos S.L., Odoo Community Association (OCA)",
    "license": "AGPL-3",
    "installable": True,
    "depends": [
        "base",
        "account",
        "queue_job",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/embat_config_data.xml",
        "views/embat_data_view.xml",
        "views/embat_api_log_views.xml",
        "views/res_partner_views.xml",

        "wizards/embat_company_wizard_views.xml",
    ],
}
