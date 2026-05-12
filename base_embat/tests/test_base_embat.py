from odoo.tests.common import TransactionCase

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
        self.assertEqual(current_env, "test")
        
        current_test_url = self.ConfigParam.get_param("embat.api_url.test")
        self.assertEqual(current_test_url, "https://api-embat-fw3hjuy3oa-ey.a.run.app/")

        url = self.embat_data._get_api_url()
        self.assertEqual(url, current_test_url)

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
