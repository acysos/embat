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
