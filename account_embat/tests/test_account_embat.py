from odoo.tests.common import TransactionCase
from unittest.mock import patch
from odoo.exceptions import UserError

class TestAccountEmbat(TransactionCase):
    def setUp(self):
        super().setUp()
        self.company = self.env.user.company_id
        
        # Enable Embat on company
        self.company.use_embat = True
        
        # Create a dummy Embat Data record
        self.embat_data = self.env["embat.data"].create({
            "name": "Test Embat API",
            "username": "user",
            "password": "password",
            "embat_company_id": "test_company_123",
        })
        self.company.embat_data_id = self.embat_data.id

        # Create res.config.settings instance
        self.config_settings = self.env['res.config.settings'].create({})

        # Create a test account
        self.test_account = self.env['account.account'].create({
            'name': 'Test Account',
            'code': '999999',
            'account_type': 'asset_cash',
            'company_ids': [(4, self.company.id)],
        })

        # Create a test analytic account
        self.test_analytic_account = self.env['account.analytic.account'].create({
            'name': 'Test Analytic Account',
            'company_id': self.company.id,
        })
        
        # Create a test partner
        self.test_partner = self.env['res.partner'].create({
            'name': 'Test Partner',
        })

        # Create a test invoice
        self.test_invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.test_partner.id,
            'invoice_date': '2025-01-01',
            'company_id': self.company.id,
            'invoice_line_ids': [
                (0, 0, {
                    'name': 'Test Product',
                    'quantity': 1,
                    'price_unit': 100.0,
                    'account_id': self.env['account.account'].search([('account_type', '=', 'income'), ('company_ids', 'in', self.company.id)], limit=1).id or self.test_account.id,
                })
            ]
        })
        self.test_invoice.action_post()

    @patch('odoo.addons.base_embat.models.embat_data.requests.post')
    @patch('odoo.addons.base_embat.models.embat_data.requests.put')
    def test_load_accounts(self, mock_put, mock_post):
        # Mock token request
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {'token': 'fake_token'}
        
        # Call the load accounts function
        self.config_settings.load_accounts()
        
        # Ensure requests were made (post for token, put for account update in Embat)
        self.assertTrue(mock_post.called)
        self.assertTrue(mock_put.called)

    @patch('odoo.addons.base_embat.models.embat_data.requests.post')
    @patch('odoo.addons.base_embat.models.embat_data.requests.put')
    def test_load_analytic_accounts(self, mock_put, mock_post):
        # Mock token request
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {'token': 'fake_token'}
        
        self.config_settings.load_analytic_accounts()
        
        self.assertTrue(mock_post.called)
        self.assertTrue(mock_put.called)

    @patch('odoo.addons.base_embat.models.embat_data.requests.post')
    @patch('odoo.addons.base_embat.models.embat_data.requests.put')
    def test_load_pending_invoices(self, mock_put, mock_post):
        # Mock token request
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {'token': 'fake_token'}
        
        self.config_settings.load_pending_invoices()
        
        self.assertTrue(mock_post.called)
        self.assertTrue(mock_put.called)

    def test_error_handling_no_data(self):
        # Test missing embat_data_id
        self.company.embat_data_id = False
        with self.assertRaises(UserError):
            self.config_settings.load_accounts()
        with self.assertRaises(UserError):
            self.config_settings.load_analytic_accounts()
        with self.assertRaises(UserError):
            self.config_settings.load_pending_invoices()
