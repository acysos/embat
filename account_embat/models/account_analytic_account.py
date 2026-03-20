# Copyright 2025 Acysos S.L. (https://www.acysos.com)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class AccountAnalyticAccount(models.Model):
    _inherit = 'account.analytic.account'

    embat_id = fields.Char(
        string="Embat ID",
        help="The ID of the analytic account in Embat.",
        readonly=True,
    )

    def _load_embat_analytic_account(self):
        for account in self:
            embat_data = account.env.company.embat_data_id
            if not embat_data:
                raise UserError(_("Please configure the Embat data first."))
            data = {
                "customId": str(account.id),
                "source": "erp",
                "active": True,
                "name": account.name,
                "type": "list",
                "values": [],
            }
            if account.embat_id:
                endpoint = "attributes/" + embat_data.embat_company_id + "/" + str(account.id)
                data.pop("analyticAccountCode", None)
                request_type = "patch"
            else:
                endpoint = "attributes/" + embat_data.embat_company_id
                request_type = "post"
            response, content = embat_data._embat_request(endpoint, account, request_type=request_type, data=data)
            if not content or "id" not in content:
                message = _("Could not retrieve the analytic account ID from Embat: %s") % (response)
                embat_data._create_log("ERROR", "ATTRIBUTES_ERROR", message, account)
                raise ValidationError(message)
            if not account.embat_id:
                account.embat_id = content["id"]
            message = _("Analytic account synced with Embat successfully: %s") % (account.embat_id)
            embat_data._create_log("INFO", "ATTRIBUTES_INFO", message, account)

    @api.model_create_multi
    def create(self, vals_list):
        res = super(AccountAnalyticAccount, self).create(vals_list)
        for account in res:
            if account.env.company.use_embat:
                account._load_embat_analytic_account()
        return res

    def write(self, vals):
        res = super(AccountAnalyticAccount, self).write(vals)
        if self.env.company.use_embat and 'embat_id' not in vals:
            self._load_embat_analytic_account()
        return res

    def _delete_embat_analytic_account(self):
        embat_data = self.env.company.embat_data_id
        if not embat_data:
            raise UserError(_("Please configure the Embat data first."))
        for account in self:
            if account.embat_id:
                endpoint = "attributes/" + embat_data.embat_company_id + "/" + account.embat_id
                response, content = embat_data._embat_request(endpoint, account, request_type="delete")
                if response.status_code not in [200, 204]:
                    message = _("Could not delete the analytic account in Embat: %s") % (response)
                    embat_data._create_log("ERROR", "ATTRIBUTES_ERROR", message, account)
                    raise ValidationError(message)
                account.embat_id = False
                message = _("Analytic account deleted in Embat with ID: %s") % (account.embat_id)
                embat_data._create_log("INFO", "ATTRIBUTES_INFO", message, account)

    def unlink(self):
        if self.env.company.use_embat:
            self._delete_embat_analytic_account()
        return super(AccountAnalyticAccount, self).unlink()
