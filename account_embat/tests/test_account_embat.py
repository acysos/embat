from odoo.tests.common import TransactionCase
from unittest.mock import patch
from odoo.exceptions import UserError

class TestAccountEmbat(TransactionCase):
    def setUp(self):
        super().setUp()
        
        # Patch requests globally for the tests
        patcher_post = patch('odoo.addons.base_embat.models.embat_data.requests.post')
        self.mock_post = patcher_post.start()
        self.addCleanup(patcher_post.stop)
        self.mock_post.return_value.status_code = 200
        self.mock_post.return_value.json.return_value = {'idToken': 'fake_token', 'id': 'fake_id'}
        self.mock_post.return_value.text = '{"idToken": "fake_token", "id": "fake_id"}'
        
        patcher_patch = patch('odoo.addons.base_embat.models.embat_data.requests.patch')
        self.mock_patch = patcher_patch.start()
        self.addCleanup(patcher_patch.stop)
        self.mock_patch.return_value.status_code = 200
        self.mock_patch.return_value.json.return_value = {'id': 'fake_id'}
        self.mock_patch.return_value.text = '{"id": "fake_id"}'
        
        patcher_get = patch('odoo.addons.base_embat.models.embat_data.requests.get')
        self.mock_get = patcher_get.start()
        self.addCleanup(patcher_get.stop)
        self.mock_get.return_value.status_code = 200
        self.mock_get.return_value.json.return_value = {'id': 'fake_id', 'data': {'id': 'fake_id'}}
        self.mock_get.return_value.text = '{"id": "fake_id", "data": {"id": "fake_id"}}'
        
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
        self.test_account = self.env['account.account'].search([('code', '=', '999999'), ('company_id', '=', self.company.id)], limit=1)
        if not self.test_account:
            self.test_account = self.env['account.account'].create({
                'name': 'Test Account',
                'code': '999999',
                'account_type': 'asset_cash',
                'company_id': self.company.id,
            })

        # Create or find a test analytic plan
        self.test_analytic_plan = self.env['account.analytic.plan'].search([], limit=1)
        if not self.test_analytic_plan:
            self.test_analytic_plan = self.env['account.analytic.plan'].create({
                'name': 'Test Plan',
            })

        # Create a test analytic account
        self.test_analytic_account = self.env['account.analytic.account'].search([('name', '=', 'Test Analytic Account'), ('company_id', '=', self.company.id)], limit=1)
        if not self.test_analytic_account:
            self.test_analytic_account = self.env['account.analytic.account'].create({
                'name': 'Test Analytic Account',
                'company_id': self.company.id,
                'plan_id': self.test_analytic_plan.id,
            })
        
        # Create a test partner
        self.test_partner = self.env['res.partner'].create({
            'name': 'Test Partner',
        })

        # Ensure an income account exists
        income_account = self.env['account.account'].search([('account_type', '=', 'income'), ('company_id', '=', self.company.id)], limit=1)
        if not income_account:
            income_account = self.env['account.account'].create({
                'name': 'Test Income',
                'code': '700000',
                'account_type': 'income',
                'company_id': self.company.id,
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
                    'account_id': income_account.id,
                })
            ]
        })
        self.test_invoice.action_post()

    def test_load_accounts(self):
        # Call the load accounts function
        self.config_settings.load_accounts()
        
        # Ensure requests were made (post for token, post for account creation in Embat)
        self.assertTrue(self.mock_post.called)

    def test_load_analytic_accounts(self):
        self.config_settings.load_analytic_accounts()
        
        self.assertTrue(self.mock_post.called)

    def test_load_pending_invoices(self):
        self.config_settings.load_pending_invoices()
        
        self.assertTrue(self.mock_post.called)

    def test_error_handling_no_data(self):
        # Test missing embat_data_id
        self.company.embat_data_id = False
        with self.assertRaises(UserError):
            self.config_settings.load_accounts()
        with self.assertRaises(UserError):
            self.config_settings.load_analytic_accounts()
        with self.assertRaises(UserError):
            self.config_settings.load_pending_invoices()
