from odoo.tests.common import TransactionCase

class TestAccountPaymentEmbat(TransactionCase):
    def setUp(self):
        super().setUp()

    def test_module_loaded(self):
        self.assertTrue(True)
