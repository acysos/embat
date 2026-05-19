# Copyright 2025 Acysos S.L. (https://www.acysos.com)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    "name": "Online Bank Statements: Embat",
    "version": "14.0.1.0.1",
    "category": "Account",
    "website": "https://github.com/OCA/bank-statement-import",
    "author": "Acysos S.L., Odoo Community Association (OCA)",
    "license": "AGPL-3",
    "installable": True,
    "depends": [
        "base_embat", "account_statement_import_online",
    ],
    "data": [
        "views/online_bank_statement_provider.xml",
    ],
}
