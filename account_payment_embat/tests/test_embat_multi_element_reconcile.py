# Copyright 2025 Acysos S.L. (https://www.acysos.com)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from unittest.mock import MagicMock, patch
from odoo.tests.common import TransactionCase


class TestEmbatMultiElementReconcile(TransactionCase):

    def setUp(self):
        super().setUp()
        self.company = self.env.user.company_id
        self.company.write({"use_embat": False})

        self.bank_account = self._get_or_create_account(
            "572094", "Bank BBVA Test", "account.data_account_type_liquidity", reconcile=False
        )
        self.suspense_account = self._get_or_create_account(
            "572994", "Cuenta Transitoria Test", "account.data_account_type_current_assets", reconcile=False
        )
        self.payable_410 = self._get_or_create_account(
            "410094", "Acreedores Test", "account.data_account_type_payable", reconcile=True
        )
        self.payable_400 = self._get_or_create_account(
            "400094", "Proveedores Test", "account.data_account_type_payable", reconcile=True
        )
        self.receivable_430 = self._get_or_create_account(
            "430094", "Clientes Test", "account.data_account_type_receivable", reconcile=True
        )
        self.income_778 = self._get_or_create_account(
            "778094", "Ingresos excepcionales Test", "account.data_account_type_other_income", reconcile=False
        )
        self.expense_668 = self._get_or_create_account(
            "668094", "Diferencias negativas de cambio Test", "account.data_account_type_expenses", reconcile=False
        )
        self.expense_purchase = self._get_or_create_account(
            "600094", "Compras Test", "account.data_account_type_expenses", reconcile=False
        )

        self.supplier = self.env["res.partner"].create(
            {
                "name": "Azure Interior Test",
                "is_company": True,
                "embat_id": "embat_partner_azure",
                "property_account_payable_id": self.payable_410.id,
                "property_account_receivable_id": self.receivable_430.id,
            }
        )

        self.bank_journal = self.env["account.journal"].create(
            {
                "name": "BBVA Test Journal",
                "type": "bank",
                "code": "BBT94",
                "embat_id": "prod_bbva_9682",
                "default_account_id": self.bank_account.id,
                "suspense_account_id": self.suspense_account.id,
                "company_id": self.company.id,
            }
        )

        self.purchase_journal = self.env["account.journal"].search(
            [("type", "=", "purchase"), ("company_id", "=", self.company.id)], limit=1
        )
        if not self.purchase_journal:
            self.purchase_journal = self.env["account.journal"].create(
                {
                    "name": "Purchase Test Journal",
                    "type": "purchase",
                    "code": "PUR94",
                    "company_id": self.company.id,
                }
            )

        self.embat_data = self.env["embat.data"].search(
            [("company_id", "=", self.company.id)], limit=1
        )
        if not self.embat_data:
            self.embat_data = self.env["embat.data"].create(
                {
                    "name": "Embat Test Config",
                    "company_id": self.company.id,
                    "username": "test@embat.io",
                    "password": "secret",
                    "embat_company_id": "comp_test_94",
                    "default_payment_account": self.suspense_account.id,
                }
            )
        else:
            self.embat_data.write(
                {
                    "embat_company_id": "comp_test_94",
                    "default_payment_account": self.suspense_account.id,
                }
            )
        self.company.embat_data_id = self.embat_data.id
        self.embat_data.embat_token = "cached_test_token"
        self.embat_data.embat_token_expiration = "2099-12-31 23:59:59"

    def _get_or_create_account(self, code, name, xml_type_ref, reconcile=False):
        acc = self.env["account.account"].search(
            [("code", "=", code), ("company_id", "=", self.company.id)], limit=1
        )
        if not acc:
            acc = self.env["account.account"].create(
                {
                    "code": code,
                    "name": name,
                    "user_type_id": self.env.ref(xml_type_ref).id,
                    "reconcile": reconcile,
                    "company_id": self.company.id,
                }
            )
        return acc

    def _create_bill(self, partner, amount, ref, payable_account=None):
        bill = self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "partner_id": partner.id,
                "ref": ref,
                "invoice_date": "2026-11-15",
                "date": "2026-11-15",
                "journal_id": self.purchase_journal.id,
                "invoice_line_ids": [
                    (
                        0,
                        0,
                        {
                            "name": ref,
                            "quantity": 1.0,
                            "price_unit": amount,
                            "account_id": self.expense_purchase.id,
                            "tax_ids": [(6, 0, [])],
                        },
                    )
                ],
            }
        )
        if payable_account:
            pay_lines = bill.line_ids.filtered(
                lambda l: l.account_id.user_type_id.type == "payable"
            )
            pay_lines.account_id = payable_account.id
        bill.action_post()
        bill.with_context(skip_embat_sync=True).embat_id = f"embat_op_{bill.id}"
        return bill

    def _create_st_line(self, amount, tx_id, concept):
        stmt = self.env["account.bank.statement"].create(
            {
                "name": f"STMT-{tx_id}",
                "date": "2026-11-15",
                "journal_id": self.bank_journal.id,
                "balance_start": 0.0,
                "balance_end_real": amount,
            }
        )
        st_line = self.env["account.bank.statement.line"].create(
            {
                "statement_id": stmt.id,
                "date": "2026-11-15",
                "payment_ref": concept,
                "amount": amount,
                "journal_id": self.bank_journal.id,
                "company_id": self.company.id,
                "unique_import_id": f"ES92-24-{tx_id}",
            }
        )
        stmt.button_post()
        return st_line

    def _mock_embat_http(self, payments_list):
        def fake_get(url, **kwargs):
            resp = MagicMock()
            resp.ok = True
            resp.status_code = 200
            if "/payments/" in url:
                data = {"data": payments_list}
            elif "/accountingentries/" in url:
                data = {"data": {"transactionsIds": ["tx_synced"]}}
            else:
                data = {"data": []}
            resp.json.return_value = data
            resp.text = str(data)
            return resp

        def fake_post(url, **kwargs):
            resp = MagicMock()
            resp.ok = True
            resp.status_code = 200
            data = {"id": "embat_entry_id_1"}
            resp.json.return_value = data
            resp.text = str(data)
            return resp

        def fake_patch(url, **kwargs):
            resp = MagicMock()
            resp.ok = True
            resp.status_code = 200
            data = {"id": "embat_patched_id_1"}
            resp.json.return_value = data
            resp.text = str(data)
            return resp

        return fake_get, fake_post, fake_patch

    def test_cases_1_2_3_4_multi_element_reconciliation(self):
        """Verify Cases 1, 2, 3, and 4 on Odoo 14.0."""
        # Case 1: 1 tx (-260) pays 2 bills (-60 and -200)
        b60 = self._create_bill(self.supplier, 60.0, "P0004", self.payable_410)
        b200 = self._create_bill(self.supplier, 200.0, "p00045", self.payable_410)
        st1 = self._create_st_line(-260.0, "tx14_case1", "2 FACTURAS")

        # Case 2: 1 tx (-200) pays 1 bill (-150) + supplier advance (-50)
        b150 = self._create_bill(self.supplier, 150.0, "F150", self.payable_410)
        st2 = self._create_st_line(-200.0, "tx14_case2", "FACTURA+PROV")

        # Case 3: 1 tx (-671) pays 1 bill (-700) + positive diff (+29) to 778
        b700 = self._create_bill(self.supplier, 700.0, "C001", self.payable_410)
        st3 = self._create_st_line(-671.0, "tx14_case3", "FACTURA+778")

        payments = [
            {
                "id": "p1a",
                "customId": "c1a",
                "type": "operations",
                "productId": "prod_bbva_9682",
                "transactionId": "tx14_case1",
                "date": "2026-11-15T00:00:00",
                "concept": "2 FACTURAS",
                "amount": -60.0,
                "accountingAmount": -60.0,
                "currency": "EUR",
                "operations": [{"customId": f"account.move-{b60.id}", "amount": -60.0}],
            },
            {
                "id": "p1b",
                "customId": "c1b",
                "type": "operations",
                "productId": "prod_bbva_9682",
                "transactionId": "tx14_case1",
                "date": "2026-11-15T00:00:00",
                "concept": "2 FACTURAS",
                "amount": -200.0,
                "accountingAmount": -200.0,
                "currency": "EUR",
                "operations": [{"customId": f"account.move-{b200.id}", "amount": -200.0}],
            },
            {
                "id": "p2a",
                "customId": "c2a",
                "type": "operations",
                "productId": "prod_bbva_9682",
                "transactionId": "tx14_case2",
                "date": "2026-11-15T00:00:00",
                "concept": "FACTURA+PROV",
                "amount": -150.0,
                "accountingAmount": -150.0,
                "currency": "EUR",
                "operations": [{"customId": f"account.move-{b150.id}", "amount": -150.0}],
            },
            {
                "id": "p2b",
                "customId": "c2b",
                "type": "contacts",
                "productId": "prod_bbva_9682",
                "transactionId": "tx14_case2",
                "contactCustomId": str(self.supplier.id),
                "date": "2026-11-15T00:00:00",
                "concept": "FACTURA+PROV",
                "amount": -50.0,
                "accountingAmount": -50.0,
                "currency": "EUR",
            },
            {
                "id": "p3a",
                "customId": "c3a",
                "type": "operations",
                "productId": "prod_bbva_9682",
                "transactionId": "tx14_case3",
                "date": "2026-11-15T00:00:00",
                "concept": "FACTURA+778",
                "amount": -700.0,
                "accountingAmount": -700.0,
                "currency": "EUR",
                "operations": [{"customId": f"account.move-{b700.id}", "amount": -700.0}],
            },
            {
                "id": "p3b",
                "customId": "c3b",
                "type": "accountings",
                "productId": "prod_bbva_9682",
                "transactionId": "tx14_case3",
                "accountingCode": self.income_778.code,
                "date": "2026-11-15T00:00:00",
                "concept": "FACTURA+778",
                "amount": 29.0,
                "accountingAmount": 29.0,
                "currency": "EUR",
            },
        ]

        fake_get, fake_post, fake_patch = self._mock_embat_http(payments)
        with patch("requests.get", side_effect=fake_get), patch(
            "requests.post", side_effect=fake_post
        ), patch("requests.patch", side_effect=fake_patch):
            self.company.use_embat = True
            self.embat_data.reconcile_payments_embat()

        self.assertEqual(b60.amount_residual, 0.0)
        self.assertEqual(b200.amount_residual, 0.0)
        self.assertEqual(b150.amount_residual, 0.0)
        self.assertEqual(b700.amount_residual, 0.0)
        self.assertTrue(st1.is_reconciled)
        self.assertTrue(st2.is_reconciled)
        self.assertTrue(st3.is_reconciled)
        inc_line = st3.move_id.line_ids.filtered(lambda l: l.account_id == self.income_778)
        self.assertEqual(inc_line.credit, 29.0)
        self.assertEqual(inc_line.debit, 0.0)
