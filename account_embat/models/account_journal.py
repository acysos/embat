# Copyright 2025 Acysos S.L. (https://www.acysos.com)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class AccountJournal(models.Model):
    _inherit = "account.journal"

    embat_id = fields.Char(
        string="Embat ID",
        help="The ID of the journal in Embat.",
        readonly=True,
    )

    def update_product_embat(self):
        """Update the Embat product for the journal."""
        self.ensure_one()
        embat_data = self.env.company.embat_data_id
        if not embat_data:
            raise UserError(_("Please configure the Embat data first."))

        response, content = embat_data._embat_request(
            "products/" + embat_data.embat_company_id,
            self,
            request_type="get",
        )
        if not content or "data" not in content:
            raise UserError(_("Could not retrieve the list of products from Embat."))
        if not self.bank_account_id:
            raise UserError(_("Please configure the bank account for this journal."))
        acc_number = self.bank_account_id.sanitized_acc_number or False
        if acc_number:
            for product in content["data"]:
                if acc_number == product['iban']:
                    self.embat_id = product['id']
                    # Update the journal name with the product name
                    endpoint = "products/" + embat_data.embat_company_id + "/" + self.embat_id
                    data = {
                        "additionalInfo": {},
                        "accountingCode": self.default_account_id.code,
                    }
                    resquest_type = "patch"
                    response, content = embat_data._embat_request(endpoint, self, request_type=resquest_type, data=data)
                    if not content or "id" not in content:
                        raise ValidationError(_("Could not retrieve the product ID from Embat."))
                    if not self.embat_id:
                        self.embat_id = content["id"]
                    return
            raise UserError(_("The bank account number does not match any product in Embat."))
        else:
            raise UserError(_("The bank account number is not set or is invalid."))


    @api.model_create_multi
    def create(self, vals_list):
        """Override create method to load Embat data after journal creation."""
        res = super(AccountJournal, self).create(vals_list)
        if self.env.company.use_embat:
            for journal in res:
                if journal.type in ['bank']:
                    journal.update_product_embat()
        return res

    def write(self, vals):
        """Override write method to update Embat data if necessary."""
        res = super(AccountJournal, self).write(vals)
        if 'embat_id' not in vals and self.env.company.use_embat:
            for journal in self:
                if journal.type in ['bank']:
                    journal.update_product_embat()
        return res

    def update_account_move_lines_asset(self):
        """Update the move lines with the Embat ID."""
        for journal in self:
            if journal.type in ['bank'] and journal.embat_id:
                move_lines = self.env['account.move.line'].search([('journal_id', '=', journal.id)])
                for line in move_lines.filtered(lambda l: l.account_id.account_type in ['asset_cash']):
                    line._load_embat_move_line_asset()

    def update_account_moves_operation(self):
        """Update the moves with the Embat ID."""
        for journal in self:
            if journal.type in ['sale', 'purchase'] and journal.embat_id:
                moves = self.env['account.move'].search([('journal_id', '=', journal.id)])
                valid_types = [
                    'out_invoice', 'in_refund', 'out_receipt',
                    'in_invoice', 'in_receipt', 'out_refund'
                ]
                valid_states = ['not_paid', 'partial']
                for move in moves.filtered(
                    lambda m: m.move_type in valid_types
                    and m.payment_state in valid_states
                ):
                        move._load_embat_move_operation()
