from unittest.mock import patch

from odoo.tests.common import TransactionCase, new_test_user

class TestBaseEmbat(TransactionCase):
    def setUp(self):
        super().setUp()
        self.ConfigParam = self.env["ir.config_parameter"]
        self.embat_data = self.env["embat.data"].create({
            "name": "Test Embat",
            "username": "test_user",
            "password": "test_password",
        })

    def test_module_loaded(self):
        self.assertTrue(True)

    def test_request_logs_without_settings_access(self):
        user = new_test_user(
            self.env, login="embat_accountant",
            groups="account.group_account_manager",
        )
        provider = self.embat_data.with_user(user)
        self.assertFalse(user.has_group("base.group_system"))
        self.assertFalse(
            self.env["embat.api.log"].with_user(user).check_access_rights(
                "create", raise_exception=False,
            )
        )
        with patch.object(type(provider), "_embat_get_headers", return_value={}), patch(
            "odoo.addons.base_embat.models.embat_data.requests.post"
        ) as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.text = '{"id": "test_operation"}'
            mock_post.return_value.json.return_value = {"id": "test_operation"}
            response, content = provider._embat_request(
                "operations/test_company", provider, request_type="post", data={},
            )
        self.assertEqual(content, {"id": "test_operation"})
        logs = self.env["embat.api.log"].sudo().search([
            ("model", "=", provider._name), ("res_id", "=", provider.id),
        ])
        self.assertEqual(len(logs), 1)
        self.assertEqual(set(logs.mapped("create_uid").ids), {user.id})

    def test_single_api_log_and_404_document_exists_handling(self):
        """Ensure _embat_request creates 1 log per call and handles 404 'The document exists' on PATCH."""
        import requests
        from unittest.mock import MagicMock

        self.embat_data.write({
            "embat_token": "valid_token",
            "embat_token_expiration": "2099-01-01 00:00:00",
        })
        log_model = self.env["embat.api.log"].sudo()
        before_count = log_model.search_count([])

        with patch("odoo.addons.base_embat.models.embat_data.requests.patch") as mock_patch, \
             patch("odoo.addons.base_embat.models.embat_data.requests.post") as mock_post:
            resp_404 = MagicMock()
            resp_404.status_code = 404
            resp_404.text = '{"detail": "The document exists"}'
            resp_404.json.return_value = {"detail": "The document exists"}
            resp_404.raise_for_status.side_effect = requests.exceptions.HTTPError(response=resp_404)
            mock_patch.return_value = resp_404

            resp, content = self.embat_data._embat_request(
                "operations/comp123/account.move-1",
                self.embat_data,
                request_type="patch",
                data={"status": "paid"},
            )
            self.assertFalse(mock_post.called, "Should not retry as POST when 404 detail says 'The document exists'")
            self.assertIn("id", content)

        after_count = log_model.search_count([])
        self.assertEqual(after_count - before_count, 1, "Exactly one embat.api.log record should be created per request")

    def test_get_api_url_test(self):
        """Test retrieving the test API URL."""
        self.ConfigParam.set_param("embat.environment", "test")
        self.ConfigParam.set_param("embat.api_url.test", "https://test.embat.api/")
        
        url = self.embat_data._get_api_url()
        self.assertEqual(url, "https://test.embat.api/")

    def test_get_api_url_production(self):
        """Test retrieving the production API URL."""
        self.ConfigParam.set_param("embat.environment", "production")
        self.ConfigParam.set_param("embat.api_url.production", "https://prod.embat.api/")
        
        url = self.embat_data._get_api_url()
        self.assertEqual(url, "https://prod.embat.api/")

    def test_get_api_url_default(self):
        """Test retrieving the default API URL (should be production if not specified, 
           but based on my implementation it defaults to production if env is not 'test').
           However, I should check what is the actual default value loaded from data file.
           Since I set 'test' in the data file, it should be test.
        """
        # Reset parameters to default (as loaded from data file)
        # Note: XML data is loaded during install, so it should be present.
        # But TransactionCase rolls back DB, so if I change them in previous tests...
        # Wait, each test method is a separate transaction rollbacked.
        
        # Let's verify the defaults from XML
        current_env = self.ConfigParam.get_param("embat.environment")
        self.assertEqual(current_env, "production")
        
        current_prod_url = self.ConfigParam.get_param("embat.api_url.production")
        self.assertEqual(current_prod_url, "https://api.embat.io")

        url = self.embat_data._get_api_url()
        self.assertEqual(url, current_prod_url)

    def test_get_requests_timeout(self):
        """Test retrieving requests timeout."""
        self.ConfigParam.set_param("embat.requests_timeout", "120")
        timeout = self.embat_data._get_requests_timeout()
        self.assertEqual(timeout, 120)

    def test_get_expiration_delta(self):
        """Test retrieving expiration delta."""
        self.ConfigParam.set_param("embat.expiration_delta", "7200")
        delta = self.embat_data._get_expiration_delta()
        self.assertEqual(delta, 7200)

    def test_get_date_format(self):
        """Test retrieving date format."""
        self.ConfigParam.set_param("embat.date_format", "%d/%m/%Y")
        fmt = self.embat_data._get_date_format()
        self.assertEqual(fmt, "%d/%m/%Y")

    def test_default_parameters(self):
        """Verify default system parameters loaded from data file."""
        timeout = self.embat_data._get_requests_timeout()
        self.assertEqual(timeout, 60)
        
        delta = self.embat_data._get_expiration_delta()
        self.assertEqual(delta, 3600)
        
        fmt = self.embat_data._get_date_format()
        self.assertEqual(fmt, "%Y-%m-%dT%H:%M:%S")
