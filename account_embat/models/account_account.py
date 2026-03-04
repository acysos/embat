# Copyright 2025 Acysos S.L. (https://www.acysos.com)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class AccountAccount(models.Model):
    _inherit = "account.account"

    embat_id = fields.Char(
        string="Embat ID",
        help="The ID of the account in Embat.",
        readonly=True,
    )

    def _load_embat_account(self):
        for account in self:
            embat_data = account.env.company.embat_data_id
            if not embat_data:
                raise UserError(_("Please configure the Embat data first."))
            data = {
                "action": True,
                "type": "banks" if account.account_type == 'asset_cash' else "accountings",
                "accountingName": account.name,
                "collective": True,
                "additionalInfo": {},
                "atributes": [],
                "accountingCode": account.code,
            }
            if account.embat_id:
                endpoint = "accountingaccounts/" + embat_data.embat_company_id + "/" + account.code
                data.pop("accountingCode", None)
                resquest_type = "patch"
            else:
                endpoint = "accountingaccounts/" + embat_data.embat_company_id
                resquest_type = "post"
            response, content = embat_data._embat_request(endpoint, account, request_type=resquest_type, data=data)
            if not content or "id" not in content:
                message = _("Could not retrieve the account ID from Embat: %s") % (response)
                embat_data._create_log("ERROR", "ACCOUNTINGS_ACCOUNTS_ERROR", message, account)
                raise ValidationError(message)
            if not account.embat_id:
                account.embat_id = content["id"]
            message = _("Account synced with Embat successfully: %s") % (account.embat_id)
            embat_data._create_log("INFO", "ACCOUNTINGS_ACCOUNTS_INFO", message, account)

    @api.model_create_multi
    def create(self, vals_list):
        res = super(AccountAccount, self).create(vals_list)
        for account in res:
            if account.env.company.use_embat:
                account._load_embat_account()
        return res

    def write(self, vals):
        res = super(AccountAccount, self).write(vals)
        if self.env.company.use_embat and 'embat_id' not in vals:
            self._load_embat_account()
        return res

    def _delete_embat_account(self):
        embat_data = self.env.company.embat_data_id
        if not embat_data:
            raise UserError(_("Please configure the Embat data first."))
        for account in self:
            if account.embat_id:
                endpoint = "accountingaccounts/" + embat_data.embat_company_id + "/" + account.code
                response, content = embat_data._embat_request(endpoint, account, request_type="delete")
                if response.status_code not in [200, 204]:
                    message = _("Could not delete the account in Embat: %s") % (response)
                    embat_data._create_log("ERROR", "ACCOUNTINGS_ACCOUNTS_ERROR", message, account)
                    raise ValidationError(_("Could not delete the account in Embat."))
                account.embat_id = False
                message = _("Account deleted in Embat with ID: %s") % (account.embat_id)
                embat_data._create_log("INFO", "ACCOUNTINGS_ACCOUNTS_INFO", message, account)

    def unlink(self):
        if self.env.company.use_embat:
            self._delete_embat_account()
        return super(AccountAccount, self).unlink()