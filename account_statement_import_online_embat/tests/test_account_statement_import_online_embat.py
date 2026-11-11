import datetime
import json
from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase


class TestAccountStatementImportOnlineEmbat(TransactionCase):
    def setUp(self):
        super().setUp()
        self.company = self.env.user.company_id
        if "use_embat" in self.company._fields:
            self.company.use_embat = False
        self.bank_journal = self.env["account.journal"].create({
            "name": "Test Embat Bank",
            "type": "bank",
            "code": "EMBB",
            "company_id": self.company.id,
        })
        self.provider = self.env["online.bank.statement.provider"].create({
            "journal_id": self.bank_journal.id,
            "service": "embat",
        })

    def test_module_loaded(self):
        self.assertTrue(True)

    def test_recompute_journal_statement_balances_after_lookback(self):
        """Ensure importing an earlier statement after a later statement cascades balances and keeps statements valid."""
        Statement = self.env["account.bank.statement"]
        # 1. Create statement for 2026-10-21 first (as happened on embat19.odoo.dev)
        stmt_day2 = Statement.create({
            "name": "EMBB/2026-10-21",
            "journal_id": self.bank_journal.id,
            "line_ids": [
                (0, 0, {
                    "date": "2026-10-21",
                    "payment_ref": "Tx Day 2",
                    "amount": 6944.21,
                    "journal_id": self.bank_journal.id,
                }),
            ],
        })
        # 2. Now create statement for earlier day 2026-10-20 (7-day lookback)
        stmt_day1 = Statement.create({
            "name": "EMBB/2026-10-20",
            "journal_id": self.bank_journal.id,
            "line_ids": [
                (0, 0, {
                    "date": "2026-10-20",
                    "payment_ref": "Tx Day 1",
                    "amount": 35999.10,
                    "journal_id": self.bank_journal.id,
                }),
            ],
        })
        # Before recompute, stmt_day2 has balance_start = 0.0 and is invalid
        self.provider._embat_recompute_journal_statement_balances()
        stmt_day1.invalidate_recordset()
        stmt_day2.invalidate_recordset()
        self.assertAlmostEqual(stmt_day1.balance_start, 0.0, places=2)
        self.assertAlmostEqual(stmt_day1.balance_end_real, 35999.10, places=2)
        self.assertAlmostEqual(stmt_day2.balance_start, 35999.10, places=2)
        self.assertAlmostEqual(stmt_day2.balance_end_real, 42943.31, places=2)
        self.assertTrue(stmt_day1.is_valid)
        self.assertTrue(stmt_day2.is_valid)
        self.assertTrue(stmt_day2.is_complete)

    def test_import_does_not_assign_own_account_number_or_partner(self):
        """Ensure Embat import does not pass the journal's own bank account as
        counterparty account_number, avoiding false partner assignment on import.
        """
        iban = "ES9121000418450200051332"
        own_bank_acc = self.env["res.partner.bank"].create({
            "acc_number": iban,
            "partner_id": self.company.partner_id.id,
        })
        self.bank_journal.bank_account_id = own_bank_acc.id
        vodafone = self.env["res.partner"].create({
            "name": "Vodafone",
            "is_company": True,
        })
        self.env["res.partner.bank"].create({
            "acc_number": iban,
            "partner_id": vodafone.id,
        })
        embat_data = self.env["embat.data"].create({
            "name": "Test Embat",
            "company_id": self.company.id,
            "username": "test@example.com",
            "password": "secret",
            "embat_company_id": "comp_test_1",
        })

        def mock_get_side_effect(url, *args, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            if "banks/" in url:
                payload = {
                    "data": [{
                        "bankProducts": [{
                            "id": "prod_test_1",
                            "accountNumber": iban,
                        }]
                    }]
                }
            elif "transactions/" in url:
                payload = {
                    "data": [{
                        "id": "tx_own_acc_regression_1",
                        "operationDate": "2026-10-20T00:00:00",
                        "valueDate": "2026-10-20T00:00:00",
                        "status": "BOOKED",
                        "product": {"id": "prod_test_1"},
                        "amount": -120.0,
                        "accountingCurrency": (
                            self.bank_journal.currency_id or self.company.currency_id
                        ).name,
                        "concept": "Pago otro proveedor",
                    }],
                    "nextPageToken": None,
                }
            else:
                payload = {"data": []}
            resp.json.return_value = payload
            resp.text = json.dumps(payload)
            return resp

        with patch(
            "odoo.addons.base_embat.models.embat_data.requests.post"
        ) as mock_post, patch(
            "odoo.addons.base_embat.models.embat_data.requests.get",
            side_effect=mock_get_side_effect,
        ):
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {
                "idToken": "fake_token",
                "id": "fake_id",
            }
            mock_post.return_value.text = '{"idToken": "fake_token", "id": "fake_id"}'

            self.provider.embat_data_id = embat_data.id
            self.provider._pull(
                datetime.datetime(2026, 10, 20, 0, 0, 0),
                datetime.datetime(2026, 10, 21, 0, 0, 0),
            )

        st_line = self.env["account.bank.statement.line"].search([
            ("journal_id", "=", self.bank_journal.id),
            ("unique_import_id", "ilike", "tx_own_acc_regression_1"),
        ])
        self.assertEqual(len(st_line), 1)
        self.assertFalse(st_line.account_number)
        self.assertFalse(st_line.partner_id)
        self.assertIn(iban, st_line.unique_import_id)
