# Copyright 2025 Acysos S.L. (https://www.acysos.com)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class ResPartner(models.Model):
    _inherit = "res.partner"

    embat_id = fields.Char(
        string="Embat ID",
        help="The ID of the partner in Embat.",
        readonly=True,
    )

    def _load_embat_partner(self):
        if self.env.company.use_embat:
            for partner in self:
                embat_data = partner.env.company.embat_data_id
                if not embat_data:
                    raise UserError(_("Please configure the Embat data first."))

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
                    "accounts": [
                    ],
                    "additionalInfo": {},
                    "attributes": [
                    ],
                    "customId": str(partner.id)
                }
                if not data["taxId"]:
                    data["taxId"] = ""
                if partner.embat_id:
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
                partner.embat_id = content["id"]
                message = _("Partner loaded in Embat with ID: %s") % (partner.embat_id)
                embat_data._create_log("INFO", "CONTACTS_INFO", message, partner)


    def _delete_embat_partner(self):
        """Delete the Embat partner if it exists."""
        embat_data = self.env.company.embat_data_id
        if not embat_data:
            raise UserError(_("Please configure the Embat data first."))
        for partner in self.filtered(lambda p: p.is_company):
            if partner.embat_id:
                endpoint = "contacts/" + embat_data.embat_company_id + "/" + str(partner.id)
                response, content = embat_data._embat_request(endpoint, partner, request_type="delete")
                if response.status_code not in [200, 204]:
                    message = _("Could not delete the partner in Embat: %s") % (response)
                    embat_data._create_log("ERROR", "CONTACTS_ERROR", message, partner)
                    raise ValidationError(message)
                partner.embat_id = False
                message = _("Partner deleted in Embat with ID: %s") % (partner.embat_id)
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
