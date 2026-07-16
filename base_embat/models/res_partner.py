# Copyright 2025 Acysos S.L. (https://www.acysos.com)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
import json


class ResPartner(models.Model):
    _inherit = "res.partner"

    embat_id = fields.Char(
        string="Embat ID",
        help="The ID of the partner in Embat.",
        readonly=True,
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
        if self.env.company.use_embat:
            for partner in self.filtered(lambda p: p.is_company):
                embat_data = partner.env.company.embat_data_id
                if not embat_data:
                    raise UserError(_("Please configure the Embat data first."))

                payments_accounts = []
                company_currency = self.env.company.currency_id.name or 'EUR'
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
                synced_for_company = False
                embat_id_dict = {}
                if partner.embat_id:
                    if partner.embat_id.startswith('{'):
                        try:
                            embat_id_dict = json.loads(partner.embat_id)
                            synced_for_company = embat_data.embat_company_id in embat_id_dict
                        except ValueError:
                            pass
                    else:
                        synced_for_company = True # Legacy behavior

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
                
                if not partner.embat_id or not partner.embat_id.startswith('{'):
                    embat_id_dict = {}
                    if partner.embat_id:
                        embat_id_dict['legacy'] = partner.embat_id
                
                embat_id_dict[embat_data.embat_company_id] = content["id"]
                partner.embat_id = json.dumps(embat_id_dict)
                message = _("Partner loaded in Embat with ID: %s") % (content["id"])
                embat_data._create_log("INFO", "CONTACTS_INFO", message, partner)


    def _delete_embat_partner(self):
        """Delete the Embat partner if it exists."""
        embat_data = self.env.company.embat_data_id
        if not embat_data:
            raise UserError(_("Please configure the Embat data first."))
        for partner in self.filtered(lambda p: p.is_company):
            synced = False
            if partner.embat_id:
                if partner.embat_id.startswith('{'):
                    try:
                        embat_id_dict = json.loads(partner.embat_id)
                        if embat_data.embat_company_id in embat_id_dict:
                            synced = True
                    except ValueError:
                        pass
                else:
                    synced = True
            
            if synced:
                endpoint = "contacts/" + embat_data.embat_company_id + "/" + str(partner.id)
                response, content = embat_data._embat_request(endpoint, partner, request_type="delete")
                if response.status_code not in [200, 204]:
                    message = _("Could not delete the partner in Embat: %s") % (response)
                    embat_data._create_log("ERROR", "CONTACTS_ERROR", message, partner)
                    raise ValidationError(message)
                
                if partner.embat_id and partner.embat_id.startswith('{'):
                    try:
                        embat_id_dict = json.loads(partner.embat_id)
                        if embat_data.embat_company_id in embat_id_dict:
                            del embat_id_dict[embat_data.embat_company_id]
                            partner.embat_id = json.dumps(embat_id_dict)
                    except ValueError:
                        partner.embat_id = False
                else:
                    partner.embat_id = False
                message = _("Partner deleted in Embat with ID: %s") % (partner.id)
                embat_data._create_log("INFO", "CONTACTS_INFO", message, partner)

    @api.model_create_multi
    def create(self, vals_list):
        res = super().create(vals_list)
        if self.env.company.use_embat:
            res._load_embat_partner()
        return res

    def write(self, vals):
        res = super().write(vals)
        if self.env.company.use_embat and 'embat_id' not in vals:
            self._load_embat_partner()
        return res

    def unlink(self):
        if self.env.company.use_embat:
            self._delete_embat_partner()
        return super().unlink()
