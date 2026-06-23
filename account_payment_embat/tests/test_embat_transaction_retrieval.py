# Copyright 2025 Acysos S.L. (https://www.acysos.com)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests.common import TransactionCase
from unittest.mock import patch, MagicMock
import json


class TestEmbatTransactionRetrieval(TransactionCase):

    def setUp(self):
        super().setUp()
        self.company = self.env.user.company_id
        # Ensure Embat is disabled initially to avoid requests during setup
        self.company.write({'use_embat': False})
        # self.company.use_embat = True  # Moved to end of setUp
        
        # Create a dummy account for default_payment_account
        self.account = self.env["account.account"].create({
            "name": "Test Account",
            "code": "123456",
            "account_type": "asset_cash",
            "company_id": self.company.id,
        })

        # Create a dummy Embat Data record
        self.embat_data = self.env["embat.data"].create({
            "name": "Test Embat",
            "company_id": self.company.id,
            "username": "test@example.com",
            "password": "password",
            "embat_company_id": "comp_123",
            "default_payment_account": self.account.id,
        })
        self.company.embat_data_id = self.embat_data.id
        # self.company.use_embat = True  # Removed from setUp, enabled locally in tests

    def test_payment_transaction_id_retrieval(self):
        """Test that payment retrieval fetches transactionId."""
        payment = self.env['account.payment'].create({
            'amount': 100.0,
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'date': '2024-01-01',
            'currency_id': self.company.currency_id.id,
        })

        # Mock requests.post and requests.get in embat.data
        # We need to patch requests used in base_embat.models.embat_data
        with patch('requests.post') as mock_post, \
             patch('requests.get') as mock_get:
            
            # Setup POST response (payment creation)
            mock_post_response = MagicMock()
            mock_post_response.ok = True
            mock_post_response.status_code = 200
            mock_post_response.text = '{"id": "pay_123"}'
            mock_post_response.json.return_value = {"id": "pay_123"}
            mock_post.return_value = mock_post_response

            # Setup GET response (transaction retrieval)
            mock_get_response = MagicMock()
            mock_get_response.ok = True
            mock_get_response.status_code = 200
            mock_get_response.text = '{"data": {"transactionId": "txn_payment_1"}}'
            mock_get_response.json.return_value = {"data": {"transactionId": "txn_payment_1"}}
            mock_get.return_value = mock_get_response

            # Enable Embat for the test
            self.company.use_embat = True
            
            # Call the method
            payment.send_payment_to_embat()

            # Verify assertions
            self.assertEqual(payment.embat_id, "pay_123", "Embat ID should be set from POST response")
            self.assertEqual(payment.embat_transaction_id, "txn_payment_1", "Transaction ID should be retrieved from GET response")
            
            # Verify calls
            # Expected POST call
            self.assertTrue(mock_post.called)
            # Expected GET call to payments/comp_123/pay_123
            self.assertTrue(mock_get.called)
            args, _ = mock_get.call_args
            self.assertIn("payments/comp_123/pay_123", args[0])

    def test_move_line_transaction_ids_retrieval(self):
        """Test that move line retrieval fetches transactionsIds."""
        # Create a journal to map to
        journal = self.env['account.journal'].create({
            'name': 'Bank Journal', 
            'type': 'bank', 
            'code': 'BNK1'
        })
        journal.embat_id = "journal_123"
        
        # Create a move line that qualifies (asset_cash)
        account = self.env['account.account'].create({
            'name': 'Bank Account',
            'code': '572000',
            'account_type': 'asset_cash',
            'reconcile': True,
        })
        
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'date': '2024-01-01',
            'journal_id': journal.id,
            'line_ids': [
                (0, 0, {
                    'name': 'Bank Line',
                    'debit': 100.0,
                    'credit': 0.0,
                    'account_id': account.id,
                }),
                (0, 0, {
                    'name': 'Counterpart',
                    'debit': 0.0,
                    'credit': 100.0,
                    'account_id': self.company.account_journal_suspense_account_id.id,
                }),
            ]
        })
        move.action_post()
        
        line = move.line_ids.filtered(lambda l: l.account_id == account)
        self.assertTrue(line, "Should have a cash line")

        # Mock requests
        with patch('requests.post') as mock_post, \
             patch('requests.get') as mock_get:
            
            # Setup POST response (entry creation)
            mock_post_response = MagicMock()
            mock_post_response.ok = True
            mock_post_response.status_code = 200
            mock_post_response.text = '{"id": "entry_456"}'
            mock_post_response.json.return_value = {"id": "entry_456"}
            mock_post.return_value = mock_post_response

            # Setup GET response (transaction retrieval)
            mock_get_response = MagicMock()
            mock_get_response.ok = True
            mock_get_response.status_code = 200
            mock_get_response.text = '{"data": {"transactionsIds": ["txn_1", "txn_2"]}}'
            mock_get_response.json.return_value = {"data": {"transactionsIds": ["txn_1", "txn_2"]}}
            mock_get.return_value = mock_get_response

            # Enable Embat for the test
            self.company.use_embat = True

            # Trigger the logic
            # create/write on move_line triggers _load_embat_move_line_asset if conditions met
            # But here we already created it. The trigger hook is on create/write/unlink.
            # So let's force call the method to test the logic in isolation
            line._load_embat_move_line_asset()

            # Verify assertions
            self.assertEqual(line.embat_id, "entry_456")
            self.assertEqual(line.embat_transaction_ids, '["txn_1", "txn_2"]', "Transaction IDs should be stored as JSON string of list")
            
            # Verify GET call
            args, _ = mock_get.call_args
            self.assertIn("accountingentries/comp_123/entry_456", args[0])

    def test_get_payment_contacts(self):
        """Test retrieving payments of type contacts creates the payment in Odoo."""
        # Create a partner/contact
        partner = self.env["res.partner"].create({
            "name": "Contact Test",
            "is_company": True,
            "embat_id": "contact_embat_123",
        })

        # Create a bank journal with embat_id
        journal = self.env['account.journal'].create({
            'name': 'Bank Contact Journal', 
            'type': 'bank', 
            'code': 'BNKC',
            'embat_id': 'product_embat_123',
        })

        payment_payload = {
            "type": "contacts",
            "productId": "product_embat_123",
            "contactCustomId": str(partner.id),
            "amount": -150.0,
            "accountingAmount": -150.0,
            "concept": "Embat Contact Payment",
            "transactionId": "txn_contact_999",
            "customId": "pay_contact_custom_123",
            "date": "2024-02-01T12:00:00Z"
        }

        # Mock Embat API patch request inside get_payment_contacts
        with patch('requests.patch') as mock_patch, \
             patch('requests.post') as mock_post, \
             patch('requests.get') as mock_get:
            
            # Setup GET response (for _load_embat_move_line_asset transaction retrieval)
            mock_get_response = MagicMock()
            mock_get_response.ok = True
            mock_get_response.status_code = 200
            mock_get_response.text = '{"data": {"transactionsIds": ["txn_contact_999"]}}'
            mock_get_response.json.return_value = {"data": {"transactionsIds": ["txn_contact_999"]}}
            mock_get.return_value = mock_get_response

            # Setup POST response (for _load_embat_move_line_asset entry creation)
            mock_post_response = MagicMock()
            mock_post_response.ok = True
            mock_post_response.status_code = 200
            mock_post_response.text = '{"id": "entry_999"}'
            mock_post_response.json.return_value = {"id": "entry_999"}
            mock_post.return_value = mock_post_response

            # Setup PATCH response (for mark_as_sync patch call)
            mock_patch_response = MagicMock()
            mock_patch_response.ok = True
            mock_patch_response.status_code = 200
            mock_patch_response.text = '{"status": "success"}'
            mock_patch_response.json.return_value = {"status": "success"}
            mock_patch.return_value = mock_patch_response

            self.company.use_embat = True
            
            # Call get_payment_contacts
            self.embat_data.get_payment_contacts(payment_payload, self.company)

            # Search for the created payment
            odoo_payment = self.env["account.payment"].search([
                ("embat_id", "=", "txn_contact_999")
            ])
            self.assertTrue(odoo_payment, "Payment should be created in Odoo")
            self.assertEqual(odoo_payment.amount, 150.0)
            self.assertEqual(odoo_payment.partner_id, partner)
            self.assertEqual(odoo_payment.payment_type, "outbound")
            self.assertEqual(odoo_payment.state, "posted")
            
            # Verify the bank statement line was created and validated/reconciled
            st_line = self.env["account.bank.statement.line"].search([
                ("payment_ref", "=", odoo_payment.name)
            ])
            self.assertTrue(st_line, "Bank statement line should be created")
            self.assertEqual(st_line.is_reconciled, True)
