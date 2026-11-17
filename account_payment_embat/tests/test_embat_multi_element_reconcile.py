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
            "572094", "Bank BBVA Test", "asset_cash", reconcile=False
        )
        self.suspense_account = self._get_or_create_account(
            "572994", "Cuenta Transitoria Test", "asset_current", reconcile=False
        )
        self.payable_410 = self._get_or_create_account(
            "410094", "Acreedores Test", "liability_payable", reconcile=True
        )
        self.payable_400 = self._get_or_create_account(
            "400094", "Proveedores Test", "liability_payable", reconcile=True
        )
        self.receivable_430 = self._get_or_create_account(
            "430094", "Clientes Test", "asset_receivable", reconcile=True
        )
        self.income_778 = self._get_or_create_account(
            "778094", "Ingresos excepcionales Test", "income_other", reconcile=False
        )
        self.expense_668 = self._get_or_create_account(
            "668094", "Diferencias negativas de cambio Test", "expense", reconcile=False
        )
        self.expense_626 = self._get_or_create_account(
            "626094", "Servicios bancarios Test", "expense", reconcile=False
        )
        self.expense_purchase = self._get_or_create_account(
            "600094", "Compras Test", "expense", reconcile=False
        )
        self.income_sales = self._get_or_create_account(
            "700094", "Ventas Test", "income", reconcile=False
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
        self.supplier_2 = self.env["res.partner"].create(
            {
                "name": "Second Supplier Test",
                "is_company": True,
                "embat_id": "embat_partner_second",
                "property_account_payable_id": self.payable_400.id,
                "property_account_receivable_id": self.receivable_430.id,
            }
        )
        self.customer = self.env["res.partner"].create(
            {
                "name": "Deco Addict Customer",
                "is_company": True,
                "embat_id": "embat_partner_customer",
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

        self.sale_journal = self.env["account.journal"].search(
            [("type", "=", "sale"), ("company_id", "=", self.company.id)], limit=1
        )
        if not self.sale_journal:
            self.sale_journal = self.env["account.journal"].create(
                {
                    "name": "Sale Test Journal",
                    "type": "sale",
                    "code": "SAL94",
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

    def _get_or_create_account(self, code, name, account_type, reconcile=False):
        acc = self.env["account.account"].search(
            [("code", "=", code), ("company_id", "=", self.company.id)], limit=1
        )
        if not acc:
            acc = self.env["account.account"].create(
                {
                    "code": code,
                    "name": name,
                    "account_type": account_type,
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
                lambda l: l.account_id.account_type == "liability_payable"
            )
            pay_lines.account_id = payable_account.id
        bill.action_post()
        bill.with_context(skip_embat_sync=True).embat_id = f"embat_op_{bill.id}"
        return bill

    def _create_customer_invoice(self, partner, amount, ref):
        inv = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": partner.id,
                "ref": ref,
                "invoice_date": "2026-11-15",
                "date": "2026-11-15",
                "journal_id": self.sale_journal.id,
                "invoice_line_ids": [
                    (
                        0,
                        0,
                        {
                            "name": ref,
                            "quantity": 1.0,
                            "price_unit": amount,
                            "account_id": self.income_sales.id,
                            "tax_ids": [(6, 0, [])],
                        },
                    )
                ],
            }
        )
        inv.action_post()
        inv.with_context(skip_embat_sync=True).embat_id = f"embat_op_{inv.id}"
        return inv

    def _create_st_line(self, amount, tx_id, concept):
        return self.env["account.bank.statement.line"].create(
            {
                "date": "2026-11-15",
                "payment_ref": concept,
                "amount": amount,
                "journal_id": self.bank_journal.id,
                "company_id": self.company.id,
                "unique_import_id": f"ES92-24-{tx_id}",
            }
        )

    def _mock_embat_http(self, payments_list):
        """Return context manager mocking requests.get / post / patch for reconcile_payments_embat."""
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

    def test_case1_one_tx_pays_two_invoices_separate_payments(self):
        """Case 1 (Jam 1): -260 EUR bank tx pays two bills (-60 EUR and -200 EUR)."""
        bill_60 = self._create_bill(self.supplier, 60.0, "P0004", self.payable_410)
        bill_200 = self._create_bill(self.supplier, 200.0, "p00045", self.payable_410)
        st_line = self._create_st_line(-260.0, "tx_case1_260", "UNA TRANSACCION / 2 FACTURAS")

        payments = [
            {
                "id": "pay_1",
                "customId": "pay_custom_1",
                "type": "operations",
                "productId": "prod_bbva_9682",
                "transactionId": "tx_case1_260",
                "date": "2026-11-15T00:00:00",
                "concept": "UNA TRANSACCION / 2 FACTURAS",
                "amount": -60.0,
                "accountingAmount": -60.0,
                "currency": "EUR",
                "operations": [
                    {
                        "customId": f"account.move-{bill_60.id}",
                        "amount": -60.0,
                        "paymentAmount": -60.0,
                    }
                ],
            },
            {
                "id": "pay_2",
                "customId": "pay_custom_2",
                "type": "operations",
                "productId": "prod_bbva_9682",
                "transactionId": "tx_case1_260",
                "date": "2026-11-15T00:00:00",
                "concept": "UNA TRANSACCION / 2 FACTURAS",
                "amount": -200.0,
                "accountingAmount": -200.0,
                "currency": "EUR",
                "operations": [
                    {
                        "customId": f"account.move-{bill_200.id}",
                        "amount": -200.0,
                        "paymentAmount": -200.0,
                    }
                ],
            },
        ]

        fake_get, fake_post, fake_patch = self._mock_embat_http(payments)
        with patch("requests.get", side_effect=fake_get), patch(
            "requests.post", side_effect=fake_post
        ) as mock_post, patch("requests.patch", side_effect=fake_patch):
            self.company.use_embat = True
            self.embat_data.reconcile_payments_embat()

        bill_60.invalidate_recordset()
        bill_200.invalidate_recordset()
        st_line.invalidate_recordset()

        self.assertEqual(bill_60.amount_residual, 0.0, "60 EUR bill must be fully reconciled")
        self.assertEqual(bill_200.amount_residual, 0.0, "200 EUR bill must be fully reconciled")
        self.assertIn(bill_60.payment_state, ("paid", "in_payment"))
        self.assertIn(bill_200.payment_state, ("paid", "in_payment"))
        self.assertTrue(st_line.is_reconciled, "Statement line must be fully reconciled")

        suspense_lines = st_line.move_id.line_ids.filtered(
            lambda l: l.account_id == self.suspense_account
        )
        self.assertFalse(suspense_lines, "No suspense lines should remain on the statement move")

        payable_lines = st_line.move_id.line_ids.filtered(
            lambda l: l.account_id == self.payable_410
        )
        self.assertEqual(len(payable_lines), 2)
        self.assertEqual(sorted(payable_lines.mapped("debit")), [60.0, 200.0])

        entry_posts = [
            c for c in mock_post.call_args_list if "/accountingentries/" in c[0][0]
        ]
        self.assertEqual(
            len(entry_posts),
            1,
            "Return bank accounting entry should be posted to Embat once fully reconciled",
        )
        self.assertEqual(entry_posts[0][1]["json"]["assetAmount"], 260.0)
        self.assertEqual(entry_posts[0][1]["json"]["transactionsIds"], ["tx_case1_260"])

    def test_case1b_single_payment_with_multiple_operations_diff_suppliers(self):
        """1 Embat payment containing 2 operations with different suppliers & payable accounts."""
        bill_1 = self._create_bill(self.supplier, 200.0, "BILL-SUP1", self.payable_410)
        bill_2 = self._create_bill(self.supplier_2, 60.0, "BILL-SUP2", self.payable_400)
        st_line = self._create_st_line(-260.0, "tx_case1b_260", "GROUPED OPS")

        payments = [
            {
                "id": "pay_grp_1",
                "customId": "pay_grp_custom_1",
                "type": "operations",
                "productId": "prod_bbva_9682",
                "transactionId": "tx_case1b_260",
                "date": "2026-11-15T00:00:00",
                "concept": "GROUPED OPS",
                "amount": -260.0,
                "accountingAmount": -260.0,
                "currency": "EUR",
                "operations": [
                    {
                        "customId": f"account.move-{bill_1.id}",
                        "amount": -200.0,
                        "paymentAmount": -200.0,
                    },
                    {
                        "customId": f"account.move-{bill_2.id}",
                        "amount": -60.0,
                        "paymentAmount": -60.0,
                    },
                ],
            }
        ]

        fake_get, fake_post, fake_patch = self._mock_embat_http(payments)
        with patch("requests.get", side_effect=fake_get), patch(
            "requests.post", side_effect=fake_post
        ), patch("requests.patch", side_effect=fake_patch):
            self.company.use_embat = True
            self.embat_data.reconcile_payments_embat()

        self.assertEqual(bill_1.amount_residual, 0.0)
        self.assertEqual(bill_2.amount_residual, 0.0)
        self.assertTrue(st_line.is_reconciled)
        self.assertFalse(st_line.partner_id, "Multi-partner st_line should leave header partner empty")
        l1 = st_line.move_id.line_ids.filtered(lambda l: l.account_id == self.payable_410)
        l2 = st_line.move_id.line_ids.filtered(lambda l: l.account_id == self.payable_400)
        self.assertEqual(l1.partner_id, self.supplier)
        self.assertEqual(l1.debit, 200.0)
        self.assertEqual(l2.partner_id, self.supplier_2)
        self.assertEqual(l2.debit, 60.0)

    def test_case2_one_tx_pays_invoice_and_remainder_to_supplier_both_orders(self):
        """Case 2 (Jam 2): -200 EUR tx pays -150 EUR bill + -50 EUR to supplier (both orders)."""
        for reverse_order in (False, True):
            tx_id = f"tx_case2_{'rev' if reverse_order else 'fwd'}"
            bill_150 = self._create_bill(self.supplier, 150.0, "FACT-150", self.payable_410)
            st_line = self._create_st_line(-200.0, tx_id, "FACTURA+PAGO A CUENTA PROVEEDOR")

            op_payment = {
                "id": f"pay_op_{tx_id}",
                "customId": f"cust_op_{tx_id}",
                "type": "operations",
                "productId": "prod_bbva_9682",
                "transactionId": tx_id,
                "date": "2026-11-15T00:00:00",
                "concept": "FACTURA+PAGO A CUENTA PROVEEDOR",
                "amount": -150.0,
                "accountingAmount": -150.0,
                "currency": "EUR",
                "operations": [
                    {
                        "customId": f"account.move-{bill_150.id}",
                        "amount": -150.0,
                        "paymentAmount": -150.0,
                    }
                ],
            }
            contact_payment = {
                "id": f"pay_ct_{tx_id}",
                "customId": f"cust_ct_{tx_id}",
                "type": "contacts",
                "productId": "prod_bbva_9682",
                "transactionId": tx_id,
                "contactCustomId": str(self.supplier.id),
                "date": "2026-11-15T00:00:00",
                "concept": "FACTURA+PAGO A CUENTA PROVEEDOR",
                "amount": -50.0,
                "accountingAmount": -50.0,
                "currency": "EUR",
            }
            payments = [contact_payment, op_payment] if reverse_order else [op_payment, contact_payment]

            fake_get, fake_post, fake_patch = self._mock_embat_http(payments)
            with patch("requests.get", side_effect=fake_get), patch(
                "requests.post", side_effect=fake_post
            ), patch("requests.patch", side_effect=fake_patch):
                self.company.use_embat = True
                self.embat_data.reconcile_payments_embat()
                self.company.use_embat = False

            bill_150.invalidate_recordset()
            st_line.invalidate_recordset()

            self.assertEqual(bill_150.amount_residual, 0.0)
            self.assertIn(bill_150.payment_state, ("paid", "in_payment"))
            self.assertTrue(st_line.is_reconciled)
            self.assertEqual(st_line.partner_id, self.supplier)

            suspense_lines = st_line.move_id.line_ids.filtered(
                lambda l: l.account_id == self.suspense_account
            )
            self.assertFalse(suspense_lines)

            payable_lines = st_line.move_id.line_ids.filtered(
                lambda l: l.account_id == self.payable_410
            )
            self.assertEqual(len(payable_lines), 2)
            reconciled_pay_line = payable_lines.filtered(lambda l: l.reconciled)
            advance_pay_line = payable_lines.filtered(lambda l: not l.reconciled)
            self.assertEqual(reconciled_pay_line.debit, 150.0)
            self.assertEqual(advance_pay_line.debit, 50.0)
            self.assertEqual(advance_pay_line.partner_id, self.supplier)

    def test_case3_one_tx_pays_invoice_and_positive_diff_to_account_both_orders(self):
        """Case 3 (Jam 3): -671 EUR tx pays -700 EUR bill + +29 EUR credit to 778 (both orders)."""
        for reverse_order in (False, True):
            tx_id = f"tx_case3_{'rev' if reverse_order else 'fwd'}"
            bill_700 = self._create_bill(self.supplier, 700.0, "C001", self.payable_410)
            st_line = self._create_st_line(-671.0, tx_id, "FACTURA+CUENTA CONTABLE")

            op_payment = {
                "id": f"pay_op_{tx_id}",
                "customId": f"cust_op_{tx_id}",
                "type": "operations",
                "productId": "prod_bbva_9682",
                "transactionId": tx_id,
                "date": "2026-11-15T00:00:00",
                "concept": "FACTURA+CUENTA CONTABLE",
                "amount": -700.0,
                "accountingAmount": -700.0,
                "currency": "EUR",
                "operations": [
                    {
                        "customId": f"account.move-{bill_700.id}",
                        "amount": -700.0,
                        "paymentAmount": -700.0,
                    }
                ],
            }
            acc_payment = {
                "id": f"pay_acc_{tx_id}",
                "customId": f"cust_acc_{tx_id}",
                "type": "accountings",
                "productId": "prod_bbva_9682",
                "transactionId": tx_id,
                "accountingCode": self.income_778.code,
                "date": "2026-11-15T00:00:00",
                "concept": "FACTURA+CUENTA CONTABLE",
                "amount": 29.0,
                "accountingAmount": 29.0,
                "currency": "EUR",
            }
            payments = [acc_payment, op_payment] if reverse_order else [op_payment, acc_payment]

            fake_get, fake_post, fake_patch = self._mock_embat_http(payments)
            with patch("requests.get", side_effect=fake_get), patch(
                "requests.post", side_effect=fake_post
            ), patch("requests.patch", side_effect=fake_patch):
                self.company.use_embat = True
                self.embat_data.reconcile_payments_embat()
                self.company.use_embat = False

            bill_700.invalidate_recordset()
            st_line.invalidate_recordset()

            self.assertEqual(
                bill_700.amount_residual, 0.0, "700 EUR bill must be 100% settled, not partial"
            )
            self.assertIn(bill_700.payment_state, ("paid", "in_payment"))
            self.assertTrue(st_line.is_reconciled)

            suspense_lines = st_line.move_id.line_ids.filtered(
                lambda l: l.account_id == self.suspense_account
            )
            self.assertFalse(suspense_lines)

            bank_line = st_line.move_id.line_ids.filtered(
                lambda l: l.account_id == self.bank_account
            )
            pay_line = st_line.move_id.line_ids.filtered(
                lambda l: l.account_id == self.payable_410
            )
            inc_line = st_line.move_id.line_ids.filtered(
                lambda l: l.account_id == self.income_778
            )
            self.assertEqual(bank_line.credit, 671.0)
            self.assertEqual(pay_line.debit, 700.0)
            self.assertTrue(pay_line.reconciled)
            self.assertEqual(inc_line.credit, 29.0)
            self.assertEqual(inc_line.debit, 0.0)

    def test_case4_one_tx_pays_invoice_and_negative_diff_to_account_both_orders(self):
        """Case 4 (Jam 4): -300 EUR tx pays -295 EUR bill + -5 EUR debit to 668 (both orders)."""
        for reverse_order in (False, True):
            tx_id = f"tx_case4_{'rev' if reverse_order else 'fwd'}"
            bill_295 = self._create_bill(self.supplier, 295.0, "V001", self.payable_410)
            st_line = self._create_st_line(-300.0, tx_id, "FACTURA+668")

            op_payment = {
                "id": f"pay_op_{tx_id}",
                "customId": f"cust_op_{tx_id}",
                "type": "operations",
                "productId": "prod_bbva_9682",
                "transactionId": tx_id,
                "date": "2026-11-15T00:00:00",
                "concept": "FACTURA+668",
                "amount": -295.0,
                "accountingAmount": -295.0,
                "currency": "EUR",
                "operations": [
                    {
                        "customId": f"account.move-{bill_295.id}",
                        "amount": -295.0,
                        "paymentAmount": -295.0,
                    }
                ],
            }
            acc_payment = {
                "id": f"pay_acc_{tx_id}",
                "customId": f"cust_acc_{tx_id}",
                "type": "accountings",
                "productId": "prod_bbva_9682",
                "transactionId": tx_id,
                "accountingCode": self.expense_668.code,
                "date": "2026-11-15T00:00:00",
                "concept": "FACTURA+668",
                "amount": -5.0,
                "accountingAmount": -5.0,
                "currency": "EUR",
            }
            payments = [acc_payment, op_payment] if reverse_order else [op_payment, acc_payment]

            fake_get, fake_post, fake_patch = self._mock_embat_http(payments)
            with patch("requests.get", side_effect=fake_get), patch(
                "requests.post", side_effect=fake_post
            ), patch("requests.patch", side_effect=fake_patch):
                self.company.use_embat = True
                self.embat_data.reconcile_payments_embat()
                self.company.use_embat = False

            self.assertEqual(bill_295.amount_residual, 0.0)
            self.assertTrue(st_line.is_reconciled)
            exp_line = st_line.move_id.line_ids.filtered(
                lambda l: l.account_id == self.expense_668
            )
            self.assertEqual(exp_line.debit, 5.0)
            self.assertEqual(exp_line.credit, 0.0)

    def test_inbound_three_elements_two_customer_invoices_and_bank_fee(self):
        """Inbound +671 EUR bank tx collects +500 EUR + +200 EUR invoices minus -29 EUR bank fee."""
        inv_500 = self._create_customer_invoice(self.customer, 500.0, "CUST-500")
        inv_200 = self._create_customer_invoice(self.customer, 200.0, "CUST-200")
        st_line = self._create_st_line(671.0, "tx_inbound_671", "COBRO 2 FACTURAS MENOS COMISION")

        payments = [
            {
                "id": "pay_in_1",
                "customId": "cust_in_1",
                "type": "operations",
                "productId": "prod_bbva_9682",
                "transactionId": "tx_inbound_671",
                "date": "2026-11-15T00:00:00",
                "concept": "COBRO 2 FACTURAS MENOS COMISION",
                "amount": 500.0,
                "accountingAmount": 500.0,
                "currency": "EUR",
                "operations": [
                    {
                        "customId": f"account.move-{inv_500.id}",
                        "amount": 500.0,
                        "paymentAmount": 500.0,
                    }
                ],
            },
            {
                "id": "pay_in_2",
                "customId": "cust_in_2",
                "type": "accountings",
                "productId": "prod_bbva_9682",
                "transactionId": "tx_inbound_671",
                "accountingCode": self.expense_626.code,
                "date": "2026-11-15T00:00:00",
                "concept": "COBRO 2 FACTURAS MENOS COMISION",
                "amount": -29.0,
                "accountingAmount": -29.0,
                "currency": "EUR",
            },
            {
                "id": "pay_in_3",
                "customId": "cust_in_3",
                "type": "operations",
                "productId": "prod_bbva_9682",
                "transactionId": "tx_inbound_671",
                "date": "2026-11-15T00:00:00",
                "concept": "COBRO 2 FACTURAS MENOS COMISION",
                "amount": 200.0,
                "accountingAmount": 200.0,
                "currency": "EUR",
                "operations": [
                    {
                        "customId": f"account.move-{inv_200.id}",
                        "amount": 200.0,
                        "paymentAmount": 200.0,
                    }
                ],
            },
        ]

        fake_get, fake_post, fake_patch = self._mock_embat_http(payments)
        with patch("requests.get", side_effect=fake_get), patch(
            "requests.post", side_effect=fake_post
        ), patch("requests.patch", side_effect=fake_patch):
            self.company.use_embat = True
            self.embat_data.reconcile_payments_embat()

        self.assertEqual(inv_500.amount_residual, 0.0)
        self.assertEqual(inv_200.amount_residual, 0.0)
        self.assertTrue(st_line.is_reconciled)
        fee_line = st_line.move_id.line_ids.filtered(
            lambda l: l.account_id == self.expense_626
        )
        self.assertEqual(fee_line.debit, 29.0)
        self.assertEqual(fee_line.credit, 0.0)

    def test_bill_and_supplier_credit_note_single_transaction(self):
        """-140 EUR bank tx settles a -200 EUR supplier bill + +60 EUR supplier credit note."""
        bill_200 = self._create_bill(self.supplier, 200.0, "BILL-200", self.payable_410)
        refund_60 = self.env["account.move"].create(
            {
                "move_type": "in_refund",
                "partner_id": self.supplier.id,
                "ref": "RFD-60",
                "invoice_date": "2026-11-15",
                "date": "2026-11-15",
                "journal_id": self.purchase_journal.id,
                "invoice_line_ids": [
                    (
                        0,
                        0,
                        {
                            "name": "RFD-60",
                            "quantity": 1.0,
                            "price_unit": 60.0,
                            "account_id": self.expense_purchase.id,
                            "tax_ids": [(6, 0, [])],
                        },
                    )
                ],
            }
        )
        refund_60.line_ids.filtered(
            lambda l: l.account_id.account_type == "liability_payable"
        ).account_id = self.payable_410.id
        refund_60.action_post()
        refund_60.with_context(skip_embat_sync=True).embat_id = f"embat_op_{refund_60.id}"

        st_line = self._create_st_line(-140.0, "tx_bill_refund_140", "FACTURA MENOS ABONO")
        payments = [
            {
                "id": "pay_br_1",
                "customId": "cust_br_1",
                "type": "operations",
                "productId": "prod_bbva_9682",
                "transactionId": "tx_bill_refund_140",
                "date": "2026-11-15T00:00:00",
                "concept": "FACTURA MENOS ABONO",
                "amount": -200.0,
                "accountingAmount": -200.0,
                "currency": "EUR",
                "operations": [
                    {
                        "customId": f"account.move-{bill_200.id}",
                        "amount": -200.0,
                        "paymentAmount": -200.0,
                    }
                ],
            },
            {
                "id": "pay_br_2",
                "customId": "cust_br_2",
                "type": "operations",
                "productId": "prod_bbva_9682",
                "transactionId": "tx_bill_refund_140",
                "date": "2026-11-15T00:00:00",
                "concept": "FACTURA MENOS ABONO",
                "amount": 60.0,
                "accountingAmount": 60.0,
                "currency": "EUR",
                "operations": [
                    {
                        "customId": f"account.move-{refund_60.id}",
                        "amount": 60.0,
                        "paymentAmount": 60.0,
                    }
                ],
            },
        ]

        fake_get, fake_post, fake_patch = self._mock_embat_http(payments)
        with patch("requests.get", side_effect=fake_get), patch(
            "requests.post", side_effect=fake_post
        ), patch("requests.patch", side_effect=fake_patch):
            self.company.use_embat = True
            self.embat_data.reconcile_payments_embat()

        self.assertEqual(bill_200.amount_residual, 0.0)
        self.assertEqual(refund_60.amount_residual, 0.0)
        self.assertTrue(st_line.is_reconciled)

    def test_foreign_currency_bill_with_positive_fx_difference(self):
        """USD bill booked at 700 EUR (770 USD @ 1.10) paid from EUR bank for -671 EUR + +29 EUR 778."""
        usd = self.env.ref("base.USD")
        usd.active = True
        self.env["res.currency.rate"].create(
            [
                {
                    "name": "2026-10-01",
                    "currency_id": usd.id,
                    "company_id": self.company.id,
                    "rate": 1.10,
                },
                {
                    "name": "2026-11-15",
                    "currency_id": usd.id,
                    "company_id": self.company.id,
                    "rate": 1.14754,
                },
            ]
        )
        usd_bill = self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "partner_id": self.supplier.id,
                "ref": "USD-BILL-770",
                "currency_id": usd.id,
                "invoice_date": "2026-10-01",
                "date": "2026-10-01",
                "journal_id": self.purchase_journal.id,
                "invoice_line_ids": [
                    (
                        0,
                        0,
                        {
                            "name": "USD Service",
                            "quantity": 1.0,
                            "price_unit": 770.0,
                            "account_id": self.expense_purchase.id,
                            "tax_ids": [(6, 0, [])],
                        },
                    )
                ],
            }
        )
        usd_bill.line_ids.filtered(
            lambda l: l.account_id.account_type == "liability_payable"
        ).account_id = self.payable_410.id
        usd_bill.action_post()
        usd_bill.with_context(skip_embat_sync=True).embat_id = f"embat_op_{usd_bill.id}"

        booked_eur = abs(usd_bill.amount_total_signed)
        st_line = self._create_st_line(-671.0, "tx_usd_fx_671", "USD FX GAIN")
        fx_gain = round(booked_eur - 671.0, 2)

        payments = [
            {
                "id": "pay_usd_op",
                "customId": "cust_usd_op",
                "type": "operations",
                "productId": "prod_bbva_9682",
                "transactionId": "tx_usd_fx_671",
                "date": "2026-11-15T00:00:00",
                "concept": "USD FX GAIN",
                "amount": -booked_eur,
                "accountingAmount": -booked_eur,
                "currency": "EUR",
                "operations": [
                    {
                        "customId": f"account.move-{usd_bill.id}",
                        "amount": -770.0,
                        "currency": "USD",
                        "paymentAmount": -booked_eur,
                    }
                ],
            },
            {
                "id": "pay_usd_fx",
                "customId": "cust_usd_fx",
                "type": "accountings",
                "productId": "prod_bbva_9682",
                "transactionId": "tx_usd_fx_671",
                "accountingCode": self.income_778.code,
                "date": "2026-11-15T00:00:00",
                "concept": "USD FX GAIN",
                "amount": fx_gain,
                "accountingAmount": fx_gain,
                "currency": "EUR",
            },
        ]

        fake_get, fake_post, fake_patch = self._mock_embat_http(payments)
        with patch("requests.get", side_effect=fake_get), patch(
            "requests.post", side_effect=fake_post
        ), patch("requests.patch", side_effect=fake_patch):
            self.company.use_embat = True
            self.embat_data.reconcile_payments_embat()

        usd_bill.invalidate_recordset()
        st_line.invalidate_recordset()
        self.assertEqual(usd_bill.amount_residual, 0.0)
        self.assertIn(usd_bill.payment_state, ("paid", "in_payment"))
        self.assertTrue(st_line.is_reconciled)
        inc_line = st_line.move_id.line_ids.filtered(
            lambda l: l.account_id == self.income_778
        )
        self.assertAlmostEqual(inc_line.credit, fx_gain, places=2)

