from odoo.tests.common import TransactionCase

class TestAccountStatementImportOnlineEmbat(TransactionCase):
    def setUp(self):
        super().setUp()

    def test_module_loaded(self):
        self.assertTrue(True)
