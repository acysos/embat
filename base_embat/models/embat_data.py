# Copyright 2025 Acysos S.L. (https://www.acysos.com)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools import DEFAULT_SERVER_DATE_FORMAT as DF
import requests
import datetime

from urllib.parse import urljoin


EMBAT_API = "https://api-embat-fw3hjuy3oa-ey.a.run.app/"
REQUESTS_TIMEOUT = 60
EMBAT_EXPIRATION_DELTA = 60 * 60  # 1 hour in seconds
EMBAT_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"


class EmbatAccount(models.Model):
    _name = "embat.data"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Data Embat"

    name = fields.Char(string="Name", required=True)
    company_id = fields.Many2one(
        comodel_name="res.company",
        default=lambda self: self.env.company,
        string="Company",
        required=True,
        help="The company to use for Embat integration.",
    )
    username = fields.Char(string="Secret ID", required=True)
    password = fields.Char(string="Secret Key", required=True)
    embat_token = fields.Char(string="Embat Token", readonly=True)
    embat_token_expiration = fields.Datetime(
        string="Embat Token Expiration", readonly=True)
    embat_company_id = fields.Char(
        string="Embat Company ID",
        help="The ID of the company to use for Embat integration.",
        readonly=True,
    )

    def _get_embat_token(self):
        """Get the Embat token for the current provider."""
        self.ensure_one()
        now = fields.Datetime.now()
        if (not self.embat_token or not self.embat_token_expiration or
                now > self.embat_token_expiration):
            endpoint = "authentication/token"
            headers = {
                "Content-Type": "application/json",
            }
            data = {
                "email": self.username,
                "password": self.password,
            }
            url = url_join(EMBAT_API, endpoint)
            try:
                response = requests.post(
                    url, json=data, headers=headers, timeout=REQUESTS_TIMEOUT)
                response.raise_for_status()
                token_data = response.json()
                self.write({
                    "embat_token": token_data.get("idToken"),
                    "embat_token_expiration": fields.Datetime.now() + datetime.timedelta(
                        seconds=EMBAT_EXPIRATION_DELTA),
                })
            except requests.RequestException as e:
                raise UserError(
                    _("Failed to retrieve Embat token: %s") % str(e))
        return self.embat_token

    def _embat_get_headers(self):
        """Method to get request headers."""
        self.ensure_one()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._get_embat_token()}",
        }
        return headers

    def _embat_request(
            self, endpoint, model, request_type="get", params=None, data=None
    ):
        content = {}
        url = url_join(EMBAT_API, endpoint)
        if request_type == "get":
            response = requests.get(
                url,
                data=data,
                params=params,
                headers=self._embat_get_headers(),
                timeout=REQUESTS_TIMEOUT,
            )
        elif request_type == "delete":
            response = requests.delete(
                url,
                data=data,
                params=params,
                headers=self._embat_get_headers(),
                timeout=REQUESTS_TIMEOUT,
            )
        elif request_type == "post":
            response = requests.post(
                url,
                json=data,
                params=params,
                headers=self._embat_get_headers(),
                timeout=REQUESTS_TIMEOUT,
            )
        elif request_type == "patch":
            response = requests.patch(
                url,
                json=data,
                params=params,
                headers=self._embat_get_headers(),
                timeout=REQUESTS_TIMEOUT,
            )
        else:
            raise UserError(_("Invalid request type: %s") % request_type)
        response.raise_for_status()
        if response.status_code == 204:
            return response, content
        try:
            content = response.json()
        except ValueError:
            model.sudo().message_post(
                body=_(
                    "Invalid JSON response from Embat API: %s" % response.text
                )
            )
        return response, content

    def action_fetch_and_select_embat_companies(self):
        self.ensure_one()
        endpoint = "companies"
        response, content = self._embat_request(endpoint, self)
        response.raise_for_status()
        if not content or "data" not in content or not content["data"]:
            raise UserError(_("No companies were found in Embat."))
        companies = content["data"]
        wizard_model = self.env["embat.company.wizard"]
        wizard_model.search([("embat_data_id", "=", self.id)]).unlink()
        for comp in companies:
            wizard_model.create({
                "name": comp.get("legalName", ""),
                "embat_id": comp["id"],
                "embat_data_id": self.id,
            })
        return {
            "type": "ir.actions.act_window",
            "name": _("Select Embat Company"),
            "res_model": "embat.company.wizard",
            "view_mode": "tree",
            "target": "new",
            "domain": [("embat_data_id", "=", self.id)],
        }

    def sync_partners(self):
        self.ensure_one()
        partners = self.env["res.partner"].search([("is_company", "=", True)])
        partners._load_embat_partner()
        return True

    def _create_log(self, level, code, message, model):
        log_vals = {
            "erp": "odoo",
            "erpVersion": self.env["ir.module.module"].search(
                [("name", "=", "base")]).installed_version,
            "connectorVersion": self.env["ir.module.module"].search(
                [("name", "=", "base_embat")]).installed_version,
            "level": level,
            "code": code,
            "message": message,
        }
        endpoint = "logs/" + self.embat_company_id
        self._embat_request(endpoint, model, request_type="post", data=log_vals)