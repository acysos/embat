from odoo.tests.common import TransactionCase


class TestAccountStatementImportOnlineEmbat(TransactionCase):
    def setUp(self):
        super().setUp()
        self.company = self.env.user.company_id
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
