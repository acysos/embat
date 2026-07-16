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
            
            if not account.plan_id:
                continue

            data = {
                "data": [
                    {
                        "customId": str(account.id),
                        "name": account.name,
                    }
                ],
            }
            # Custom ID of the attribute is the plan_id
            plan_custom_id = str(account.plan_id.id)
            
            endpoint = "attributes/" + embat_data.embat_company_id + "/" + plan_custom_id + "/values/bulk"
            response, content = embat_data._embat_request(endpoint, account, request_type="post", data=data)
            
            if response.status_code == 404:
                # The attribute doesn't exist, we need to create it
                create_data = {
                    "customId": plan_custom_id,
                    "name": account.plan_id.name,
                    "source": "erp",
                    "active": True,
                    "type": "list",
                    "values": data["data"]
                }
                create_endpoint = "attributes/" + embat_data.embat_company_id
                response, content = embat_data._embat_request(create_endpoint, account, request_type="post", data=create_data)

            if response.status_code not in [200, 201, 204] or not content:
                message = _("Could not sync the analytic account with Embat: %s") % (response.text)
                embat_data._create_log("ERROR", "ATTRIBUTES_ERROR", message, account)
                raise ValidationError(message)

            # We can use the content ID as embat_id or simply mark it as synced.
            # Assuming the response is the attribute object, we save its ID, or we just save a placeholder if not present
            if not account.embat_id:
                account.embat_id = content.get("id") or plan_custom_id
                
            message = _("Analytic account synced with Embat successfully: %s") % (account.name)
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
            if account.embat_id and account.plan_id:
                plan_custom_id = str(account.plan_id.id)
                endpoint = "attributes/" + embat_data.embat_company_id + "/" + plan_custom_id + "/values"
                data = {
                    "data": [
                        {"customId": str(account.id)}
                    ]
                }
                response, content = embat_data._embat_request(endpoint, account, request_type="delete", data=data)
                if response.status_code not in [200, 204, 404]:
                    message = _("Could not delete the analytic account in Embat: %s") % (response.text)
                    embat_data._create_log("ERROR", "ATTRIBUTES_ERROR", message, account)
                    raise ValidationError(message)
                account.embat_id = False
                message = _("Analytic account deleted in Embat: %s") % (account.name)
                embat_data._create_log("INFO", "ATTRIBUTES_INFO", message, account)

    def unlink(self):
        if self.env.company.use_embat:
            self._delete_embat_analytic_account()
        return super(AccountAnalyticAccount, self).unlink()
