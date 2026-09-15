# Copyright 2025 Acysos S.L. (https://www.acysos.com)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
import requests


class AccountAnalyticAccount(models.Model):
    _inherit = 'account.analytic.account'

    embat_id = fields.Char(
        string="Embat ID",
        help="The ID of the analytic account in Embat for the current company.",
        compute="_compute_embat_id",
        search="_search_embat_id",
    )

    @api.depends("embat_mapping_ids")
    def _compute_embat_id(self):
        for account in self:
            mapping = account.embat_mapping_ids.filtered(lambda m: m.company_id == self.env.company)
            account.embat_id = mapping[0].embat_id if mapping else False

    def _search_embat_id(self, operator, value):
        if operator == "=":
            mappings = self.env["embat.analytic.account.mapping"].sudo().search([
                ("embat_id", operator, value),
                ("company_id", "in", self.env.companies.ids)
            ])
            return [("id", "in", mappings.mapped("analytic_account_id").ids)]
        elif operator in ("!=", "not ilike", "not in"):
            return [("embat_mapping_ids.embat_id", operator, value)]
        else:
            return [("embat_mapping_ids.embat_id", operator, value)]

    embat_mapping_ids = fields.One2many(
        comodel_name="embat.analytic.account.mapping",
        inverse_name="analytic_account_id",
        string="Embat Mappings",
    )

    def _load_embat_analytic_account(self):
        import json
        for account in self:
            if not account.plan_id:
                continue

            if account.company_id:
                embat_datas = account.company_id.embat_data_id
            else:
                embat_datas = account.env['embat.data'].sudo().search([('embat_company_id', '!=', False)])
            
            if not embat_datas:
                continue

            plan_custom_id = str(account.plan_id.id)
            value_dict = {
                "customId": str(account.id),
                "name": account.name,
                "parentCustomId": plan_custom_id,
            }

            data_values = {
                "data": [value_dict],
            }

            for embat_data in embat_datas:
                # Check if attribute exists
                check_endpoint = "attributes/" + embat_data.embat_company_id + "/" + plan_custom_id
                try:
                    check_response, dummy_content = embat_data._embat_request(check_endpoint, account, request_type="get")
                except requests.exceptions.HTTPError as e:
                    if e.response.status_code == 404:
                        check_response = e.response
                        dummy_content = None
                    else:
                        raise e
                
                if check_response.status_code == 200:
                    # The attribute exists, add values to it
                    endpoint = "attributes/" + embat_data.embat_company_id + "/" + plan_custom_id + "/values/bulk"
                    response, content = embat_data._embat_request(endpoint, account, request_type="post", data=data_values)
                elif check_response.status_code == 404:
                    # The attribute doesn't exist, we create it using bulk
                    create_data = {
                        "data": [
                            {
                                "customId": plan_custom_id,
                                "name": account.plan_id.name,
                                "source": "erp",
                                "active": True,
                                "type": "list",
                                "values": data_values["data"]
                            }
                        ]
                    }
                    create_endpoint = "attributes/" + embat_data.embat_company_id + "/bulk"
                    response, content = embat_data._embat_request(create_endpoint, account, request_type="post", data=create_data)
                else:
                    response = check_response
                    content = dummy_content

                if response.status_code not in [200, 201, 204] or not content:
                    message = _("Could not sync the analytic account with Embat: %s") % (response.text)
                    embat_data._create_log("ERROR", "ATTRIBUTES_ERROR", message, account)
                    raise ValidationError(message)

                comp = embat_data.company_id
                mapping = account.embat_mapping_ids.filtered(lambda m: m.company_id == comp)
                synced_for_company = bool(mapping)

                # --- LEGACY MIGRATION SCRIPT (Commented out) ---
                # if not synced_for_company:
                #     self.env.cr.execute("SELECT embat_id FROM account_analytic_account WHERE id = %s", [account.id])
                #     legacy_val = self.env.cr.fetchone()
                #     legacy_embat_id = legacy_val[0] if legacy_val else False
                #     
                #     if legacy_embat_id:
                #         if legacy_embat_id.startswith('{'):
                #             try:
                #                 embat_id_dict = json.loads(legacy_embat_id)
                #                 if embat_data.embat_company_id in embat_id_dict:
                #                     synced_for_company = True
                #                     account.embat_mapping_ids = [(0, 0, {
                #                         'company_id': comp.id,
                #                         'embat_id': embat_id_dict[embat_data.embat_company_id]
                #                     })]
                #             except ValueError:
                #                 pass
                #         else:
                #             synced_for_company = True
                #             account.embat_mapping_ids = [(0, 0, {
                #                 'company_id': comp.id,
                #                 'embat_id': legacy_embat_id
                #             })]
                # -----------------------------------------------

                if not synced_for_company:
                    account.embat_mapping_ids = [(0, 0, {
                        'company_id': comp.id,
                        'embat_id': plan_custom_id,
                    })]

                message = _("Analytic account synced with Embat successfully: %s") % (account.name)
                embat_data._create_log("INFO", "ATTRIBUTES_INFO", message, account)

    @api.model_create_multi
    def create(self, vals_list):
        res = super(AccountAnalyticAccount, self).create(vals_list)
        for account in res:
            account._load_embat_analytic_account()
        return res

    def write(self, vals):
        res = super(AccountAnalyticAccount, self).write(vals)
        if 'embat_id' not in vals:
            self._load_embat_analytic_account()
        return res

    def _delete_embat_analytic_account(self):
        for account in self:
            if not account.plan_id:
                continue

            if account.company_id:
                embat_datas = account.company_id.embat_data_id
            else:
                embat_datas = account.env['embat.data'].sudo().search([('embat_company_id', '!=', False)])

            plan_custom_id = str(account.plan_id.id)
            for embat_data in embat_datas:
                comp = embat_data.company_id
                mapping = account.embat_mapping_ids.filtered(lambda m: m.company_id == comp)
                synced = bool(mapping)
                
                # --- LEGACY MIGRATION SCRIPT (Commented out) ---
                # if not synced:
                #     self.env.cr.execute("SELECT embat_id FROM account_analytic_account WHERE id = %s", [account.id])
                #     legacy_val = self.env.cr.fetchone()
                #     legacy_embat_id = legacy_val[0] if legacy_val else False
                #     
                #     if legacy_embat_id:
                #         if legacy_embat_id.startswith('{'):
                #             try:
                #                 embat_id_dict = json.loads(legacy_embat_id)
                #                 if embat_data.embat_company_id in embat_id_dict:
                #                     synced = True
                #             except ValueError:
                #                 pass
                #         else:
                #             synced = True
                # -----------------------------------------------

                if not synced:
                    continue

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
                
                if mapping:
                    mapping.unlink()
                    
                # --- LEGACY CLEANUP (Commented out) ---
                # self.env.cr.execute("UPDATE account_analytic_account SET embat_id = NULL WHERE id = %s", [account.id])
                # --------------------------------------

                message = _("Analytic account deleted in Embat: %s") % (account.name)
                embat_data._create_log("INFO", "ATTRIBUTES_INFO", message, account)

    def unlink(self):
        self._delete_embat_analytic_account()
        return super(AccountAnalyticAccount, self).unlink()
