# Copyright 2025 Acysos S.L. (https://www.acysos.com)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
import datetime


EMBAT_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    embat_id = fields.Char(
        string="Embat ID",
        help="The ID of the move line in Embat.",
        readonly=True,
    )

    def _prepare_embat_move_line_data(self, embat_format_date):
        self.ensure_one()
        data = {
            "accountingCode": self.account_id.code,
            "counterpartAccountingCode": None,
            "accountingName": self.account_id.name,
            "counterpartAccountingName": None,
            "assetAmount": self.credit,
            "balance": None,
            "liabilityAmount": self.debit,
            "description": self.name,
            "date": embat_format_date,
            "customId": str(self.id),
        }

        if self.statement_line_id:
            data['transactionsIds'] = self.statement_line_id.unique_import_id
        elif (hasattr(self.move_id, "embat_transaction_id") and
              self.move_id.embat_transaction_id):
            data['transactionsIds'] = self.move_id.embat_transaction_id

        return data

    def _load_embat_move_line_asset(self):
        if self.env.company.use_embat:
            for line in self:
                embat_data = line.env.company.embat_data_id
                if not embat_data:
                    raise UserError(_("Please configure the Embat data first."))
                date_value = (
                    line.date or line.move_id.date or
                    fields.Date.context_today(line))
                if isinstance(date_value, str):
                    date_obj = fields.Date.from_string(date_value)
                else:
                    date_obj = date_value
                embat_format_date = date_obj.strftime(EMBAT_DATE_FORMAT)

                data = line._prepare_embat_move_line_data(embat_format_date)

                if line.embat_id:
                    endpoint = "accountingentries/" + embat_data.embat_company_id + "/" + line.embat_id
                    request_type = "patch"
                else:
                    endpoint = "accountingentries/" + embat_data.embat_company_id
                    request_type = "post"
                response, content = embat_data._embat_request(endpoint, line, request_type=request_type, data=data)
                if not content or "id" not in content:
                    message = _("Could not retrieve the move line ID from Embat: %s") % (response)
                    embat_data._create_log("ERROR", "ACCOUNTINGS_ENTRIES_ERROR", message, line)
                    raise ValidationError(message)
                line.embat_id = content["id"]
                message = _("Move line synced with Embat successfully: %s") % (line.embat_id)
                embat_data._create_log("INFO", "ACCOUNTINGS_ENTRIES_INFO", message, line)

    def _delete_embat_move_line_asset(self):
        """Delete the Embat move line if it exists."""
        for line in self:
            if line.embat_id:
                embat_data = line.env.company.embat_data_id
                if not embat_data:
                    raise UserError(_("Please configure the Embat data first."))
                endpoint = "accountingentries/" + embat_data.embat_company_id + "/" + str(line.id)
                response, content = embat_data._embat_request(endpoint, line, request_type="delete")
                if response.status_code != 200:
                    message = _("Could not delete the move line in Embat: %s") % (response)
                    embat_data._create_log("ERROR", "ACCOUNTINGS_ENTRIES_ERROR", message, line)
                    raise ValidationError(message)
                line.embat_id = False
                message = _("Move line deleted in Embat with ID: %s") % (line.embat_id)
                embat_data._create_log("INFO", "ACCOUNTINGS_ENTRIES_INFO", message, line)

    @api.model_create_multi
    def create(self, vals_list):
        """Override create method to load Embat data after move line creation."""
        res = super(AccountMoveLine, self).create(vals_list)
        if self.env.company.use_embat:
            for line in res:
                if line.journal_id and line.journal_id.embat_id and line.account_id.account_type in ['asset_cash']:
                    line._load_embat_move_line_asset()
        return res

    def write(self, vals):
        """Override write method to load Embat data after move line update."""
        res = super(AccountMoveLine, self).write(vals)
        if self.env.company.use_embat and 'embat_id' not in vals:
            for line in self:
                if line.journal_id and line.journal_id.embat_id and line.account_id.account_type in ['asset_cash']:
                    line._load_embat_move_line_asset()
        return res

    def unlink(self):
        """Override unlink method to delete Embat move line if it exists."""
        if self.env.company.use_embat:
            for line in self:
                if line.journal_id and line.journal_id.embat_id and line.account_id.account_type in ['asset_cash']:
                    line._delete_embat_move_line_asset()
        return super(AccountMoveLine, self).unlink()