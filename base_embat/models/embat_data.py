# Copyright 2025 Acysos S.L. (https://www.acysos.com)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools import DEFAULT_SERVER_DATE_FORMAT as DF
import requests
import datetime
import json

from werkzeug.urls import url_join

import logging

_logger = logging.getLogger(__name__)



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
    embat_token_expiration = fields.Datetime(string="Embat Token Expiration", readonly=True)
    embat_company_id = fields.Char(
        string="Embat Company ID",
        help="The ID of the company to use for Embat integration.",
        readonly=True,
    )

    def _get_api_url(self):
        """Get the Embat API URL based on the system parameter."""
        Config = self.env["ir.config_parameter"].sudo()
        environment = Config.get_param("embat.environment", "production")
        if environment == "test":
            return Config.get_param("embat.api_url.test")
        return Config.get_param("embat.api_url.production")

    def _get_requests_timeout(self):
        return int(self.env["ir.config_parameter"].sudo().get_param("embat.requests_timeout", 60))

    def _get_expiration_delta(self):
        return int(self.env["ir.config_parameter"].sudo().get_param("embat.expiration_delta", 3600))

    def _get_date_format(self):
        return self.env["ir.config_parameter"].sudo().get_param("embat.date_format", "%Y-%m-%dT%H:%M:%S")

    def _get_embat_token(self):
        """Get the Embat token for the current provider."""
        self.ensure_one()
        now = fields.Datetime.now()
        if not self.embat_token or not self.embat_token_expiration or now > self.embat_token_expiration:
            endpoint = "authentication/token"
            headers = {
                "Content-Type": "application/json",
            }
            data = {
                "email": self.username,
                "password": self.password,
            }
            url = url_join(self._get_api_url(), endpoint)
            try:
                response = requests.post(url, json=data, headers=headers, timeout=self._get_requests_timeout())
                response.raise_for_status()
                token_data = response.json()
                self.write({
                    "embat_token": token_data.get("idToken"),
                    "embat_token_expiration": fields.Datetime.now() + datetime.timedelta(seconds=self._get_expiration_delta()),
                })
            except requests.RequestException as e:
                raise UserError(
                    _("Failed to retrieve Embat token: %s") % str(e)
                ) from e
        return self.embat_token

    def _embat_get_headers(self):
        """Method to get request headers."""
        self.ensure_one()
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer %s" % self._get_embat_token(),
        }
        return headers

    def _embat_request(
            self, endpoint, model, request_type="get", params=None, data=None
    ):
        content = {}
        headers = self._embat_get_headers()
        url = url_join(self._get_api_url(), endpoint)
        if request_type == "get":
            response = requests.get(
                url,
                data=data,
                params=params,
                headers=headers,
                timeout=self._get_requests_timeout(),
            )
        elif request_type == "delete":
            response = requests.delete(
                url,
                data=data,
                params=params,
                headers=headers,
                timeout=self._get_requests_timeout(),
            )
        elif request_type == "post":
            response = requests.post(
                url,
                json=data,
                params=params,
                headers=headers,
                timeout=self._get_requests_timeout(),
            )
        elif request_type == "patch":
            response = requests.patch(
                url,
                json=data,
                params=params,
                headers=headers,
                timeout=self._get_requests_timeout(),
            )
        else:
            raise UserError(_("Invalid request type: %s") % request_type)
        log_vals = {
            'name': url,
            'model': model._name,
            'res_id': model.id if isinstance(model.id, int) and type(model.id).__name__ != 'NewId' else 0,
            'request_type': request_type,
            'params': json.dumps(params, indent=4) if params else False,
            'headers': json.dumps(headers, indent=4),
            'data': json.dumps(data, indent=4) if data else False,
            'response': response.text,
        }
        _logger.info(json.dumps(log_vals, indent=4))
        self.env['embat.api.log'].create(log_vals)

        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            if request_type == "patch" and response.status_code == 404:
                new_endpoint = endpoint.rsplit('/', 1)[0]
                _logger.warning("Resource not found (404) during PATCH on %s. Retrying as POST on %s", endpoint, new_endpoint)
                return self._embat_request(new_endpoint, model, request_type="post", params=params, data=data)
            raise e
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
        self.env['embat.api.log'].create({
            'name': url,
            'model': model._name,
            'res_id': model.id if isinstance(model.id, int) and type(model.id).__name__ != 'NewId' else 0,
            'request_type': request_type,
            'params': json.dumps(params, indent=4) if params else False,
            'headers': json.dumps(headers, indent=4),
            'data': json.dumps(data, indent=4) if data else False,
            'response': json.dumps(content, indent=4) if content else False,
        })
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
            "view_mode": "list",
            "target": "new",
            "domain": [("embat_data_id", "=", self.id)],
        }

    def sync_partners(self):
        self.ensure_one()
        partners = self.env["res.partner"].search([])
        partners._load_embat_partner()
        return True

    def _create_log(self, level, code, message, model):
        log_vals = {
            "erp": "odoo",
            "erpVersion": self.env["ir.module.module"].search([("name", "=", "base")]).installed_version,
            "connectorVersion": self.env["ir.module.module"].search([("name", "=", "base_embat")]).installed_version,
            "level": level,
            "code": code,
            "message": message,
        }
        endpoint = "logs/" + self.embat_company_id
        self._embat_request(endpoint, model, request_type="post", data=log_vals)