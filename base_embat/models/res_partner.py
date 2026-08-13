# Copyright 2025 Acysos S.L. (https://www.acysos.com)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
import json


class ResPartner(models.Model):
    _inherit = "res.partner"

    embat_id = fields.Char(
        string="Embat ID",
        help="The ID of the partner in Embat for the current company.",
        compute="_compute_embat_id",
        search="_search_embat_id",
    )

    @api.depends("embat_mapping_ids")
    def _compute_embat_id(self):
        for partner in self:
            mapping = partner.embat_mapping_ids.filtered(lambda m: m.company_id == self.env.company)
            partner.embat_id = mapping[0].embat_id if mapping else False

    def _search_embat_id(self, operator, value):
        if operator == "=":
            mappings = self.env["embat.partner.mapping"].sudo().search([
                ("embat_id", operator, value),
                ("company_id", "in", self.env.companies.ids)
            ])
            return [("id", "in", mappings.mapped("partner_id").ids)]
        elif operator in ("!=", "not ilike", "not in"):
            return [("embat_mapping_ids.embat_id", operator, value)]
        else:
            return [("embat_mapping_ids.embat_id", operator, value)]

    embat_mapping_ids = fields.One2many(
        comodel_name="embat.partner.mapping",
        inverse_name="partner_id",
        string="Embat Mappings",
    )


    embat_api_log_ids = fields.Many2many(
        comodel_name="embat.api.log",
        compute="_compute_embat_api_log_ids",
        string="Embat API Logs",
    )

    def _compute_embat_api_log_ids(self):
        for record in self:
            domain = [
                ("model", "=", record._name),
                ("res_id", "=", record.id),
            ]
            record.embat_api_log_ids = self.env["embat.api.log"].search(domain)

    def _load_embat_partner(self):
        for partner in self.filtered(lambda p: p.is_company):
            target_companies = partner.company_id if partner.company_id else self.env["res.company"].search([("use_embat", "=", True)])
            for comp in target_companies.filtered("use_embat"):
                embat_data = comp.embat_data_id
                if not embat_data:
                    raise UserError(_("Please configure the Embat data first for company %s.") % comp.name)

                payments_accounts = []
                company_currency = comp.currency_id.name or 'EUR'
                for bank in partner.bank_ids.filtered('sanitized_acc_number'):
                    details = {"iban": bank.sanitized_acc_number}
                    if bank.bank_id and bank.bank_id.bic:
                        details["bic"] = bank.bank_id.bic
                        details["swift"] = bank.bank_id.bic
                    if bank.bank_id and bank.bank_id.country:
                        details["bankCountryCode"] = bank.bank_id.country.code
                    
                    account_data = {
                        "default": False,
                        "details": details,
                        "currency": bank.currency_id.name if bank.currency_id else company_currency,
                    }
                    payments_accounts.append(account_data)

                data = {
                    "tradeName": partner.name,
                    "legalName": partner.name,
                    "taxId": partner.vat if partner.vat and (
                            not partner.parent_id or not partner.parent_id.vat) else partner.parent_id.vat,
                    "contact": {
                        "phone": str(partner.phone) if partner.phone else "",
                        "email": partner.email if partner.email else "",
                        "name": partner.name,
                        "surname": partner.name
                    },
                    "address": {
                        "postalCode": str(partner.zip) if partner.zip else "",
                        "address": partner.street if partner.street else "",
                        "province": partner.state_id.name if partner.state_id else "",
                        "city": partner.city if partner.city else "",
                        "country": partner.country_id.name if partner.country_id else ""
                    },
                    "contactType": "company" if partner.company_type == "company" else "freelance",
                    "type": "client-supplier",
                    "paymentsAccounts": payments_accounts,
                    "additionalInfo": {},
                    "attributes": [
                    ],
                    "customId": str(partner.id)
                }
                if not data["taxId"]:
                    data["taxId"] = ""
                # Check if it was synced for this Embat company
                mapping = partner.embat_mapping_ids.filtered(lambda m: m.company_id == comp)
                synced_for_company = bool(mapping)

                if synced_for_company:
                    endpoint = "contacts/" + embat_data.embat_company_id + "/" + str(partner.id)
                    request_type = "patch"
                else:
                    endpoint = "contacts/" + embat_data.embat_company_id
                    request_type = "post"

                response, content = embat_data._embat_request(endpoint, partner, request_type=request_type, data=data)
                if not content or "id" not in content:
                    message = _("Error loading partner in Embat: %s") % (response)
                    embat_data._create_log("ERROR", "CONTACTS_ERROR", message, partner)
                    raise UserError(message)
                
                if not synced_for_company:
                    # --- LEGACY MIGRATION SCRIPT (Commented out) ---
                    # If you have production data using the old JSON approach, you can uncomment this
                    # to auto-migrate the data. We use raw SQL because the field is now 'computed'
                    # and the ORM will not read the old physical column value.
                    #
                    # self.env.cr.execute("SELECT embat_id FROM res_partner WHERE id = %s", [partner.id])
                    # legacy_val = self.env.cr.fetchone()
                    # legacy_embat_id = legacy_val[0] if legacy_val else False
                    # 
                    # if legacy_embat_id:
                    #     if legacy_embat_id.startswith('{'):
                    #         try:
                    #             embat_id_dict = json.loads(legacy_embat_id)
                    #             if embat_data.embat_company_id in embat_id_dict:
                    #                 synced_for_company = True
                    #                 partner.embat_mapping_ids = [(0, 0, {
                    #                     'company_id': comp.id,
                    #                     'embat_id': embat_id_dict[embat_data.embat_company_id]
                    #                 })]
                    #         except ValueError:
                    #             pass
                    #     else:
                    #         synced_for_company = True
                    #         partner.embat_mapping_ids = [(0, 0, {
                    #             'company_id': comp.id,
                    #             'embat_id': legacy_embat_id
                    #         })]
                    # -----------------------------------------------
                    partner.embat_mapping_ids = [(0, 0, {
                        'company_id': comp.id,
                        'embat_id': content["id"],
                    })]
                    
                message = _("Partner loaded in Embat with ID: %s") % (content["id"])
                embat_data._create_log("INFO", "CONTACTS_INFO", message, partner)


    def _delete_embat_partner(self):
        """Delete the Embat partner if it exists."""
        for partner in self.filtered(lambda p: p.is_company):
            target_companies = partner.company_id if partner.company_id else self.env["res.company"].search([("use_embat", "=", True)])
            for comp in target_companies.filtered("use_embat"):
                embat_data = comp.embat_data_id
                if not embat_data:
                    raise UserError(_("Please configure the Embat data first for company %s.") % comp.name)

                mapping = partner.embat_mapping_ids.filtered(lambda m: m.company_id == comp)
                synced = bool(mapping)
                
                # --- LEGACY MIGRATION SCRIPT (Commented out) ---
                # if not synced:
                #     self.env.cr.execute("SELECT embat_id FROM res_partner WHERE id = %s", [partner.id])
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
                
                if synced:
                    endpoint = "contacts/" + embat_data.embat_company_id + "/" + str(partner.id)
                    response, content = embat_data._embat_request(endpoint, partner, request_type="delete")
                    if response.status_code not in [200, 204]:
                        message = _("Could not delete the partner in Embat: %s") % (response)
                        embat_data._create_log("ERROR", "CONTACTS_ERROR", message, partner)
                        raise ValidationError(message)
                    
                    if mapping:
                        mapping.unlink()
                        
                    # --- LEGACY CLEANUP (Commented out) ---
                    # Clean legacy field directly
                    # self.env.cr.execute("UPDATE res_partner SET embat_id = NULL WHERE id = %s", [partner.id])
                    # --------------------------------------
                        
                    message = _("Partner deleted in Embat with ID: %s") % (partner.id)
                    embat_data._create_log("INFO", "CONTACTS_INFO", message, partner)

    @api.model_create_multi
    def create(self, vals_list):
        res = super().create(vals_list)
        res._load_embat_partner()
        return res

    def write(self, vals):
        res = super().write(vals)
        if 'embat_id' not in vals:
            self._load_embat_partner()
        return res

    def unlink(self):
        self._delete_embat_partner()
        return super().unlink()
