# Copyright 2025 Acysos S.L. (https://www.acysos.com)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    "name": "Account Reconcile: Embat",
    "version": "17.0.1.0.1",
    "category": "Account",
    "website": "https://github.com/OCA/account-reconcile",
    "author": "Acysos S.L., Odoo Community Association (OCA)",
    "license": "AGPL-3",
    "installable": True,
    "depends": [
        "base_embat", "account", "account_embat",
    ],
    "data": [
        "views/embat_data_views.xml",
        "views/account_payment_views.xml",

        "data/embat_data_cron.xml",
    ],
}
