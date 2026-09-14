# Part of iKiKu. Licensed under AGPL-3.0.
import secrets

from odoo import fields, models

from odoo.addons.sms_kavenegar.tools import kavenegar
from odoo.addons.sms_kavenegar.tools.kavenegar import KavenegarClient, KavenegarError
from odoo.addons.sms_kavenegar.tools.sms_api import SmsApiKavenegar


class ResCompany(models.Model):
    _inherit = 'res.company'

    sms_kavenegar_enabled = fields.Boolean("Send SMS via Kavenegar")
    sms_kavenegar_api_key = fields.Char("Kavenegar API key", groups='base.group_system', copy=False)
    sms_kavenegar_sender = fields.Char("Kavenegar sender line",
                                       help="The line number messages are sent from, e.g. 10004346.")
    sms_kavenegar_otp_template = fields.Char(
        "Kavenegar OTP template", help="Name of a verify/lookup template approved in the Kavenegar panel, "
                                       "with %token where the code goes.")
    sms_kavenegar_callback_token = fields.Char(
        "Kavenegar callback token", groups='base.group_system', copy=False,
        default=lambda self: secrets.token_hex(16))

    def _get_sms_api_class(self):
        self.ensure_one()
        if self.sms_kavenegar_enabled:
            return SmsApiKavenegar
        return super()._get_sms_api_class()

    def _sms_kavenegar_client(self):
        """`sms_kavenegar.endpoint` exists so a test can point the client at a stub."""
        self.ensure_one()
        endpoint = self.env['ir.config_parameter'].sudo().get_param('sms_kavenegar.endpoint')
        return KavenegarClient(self.sudo().sms_kavenegar_api_key, endpoint=endpoint or kavenegar.API_ROOT)

    def _sms_kavenegar_callback_url(self):
        self.ensure_one()
        return '%s/sms_kavenegar/status/%s' % (self.get_base_url(), self.sudo().sms_kavenegar_callback_token)

    def _sms_kavenegar_otp_ready(self):
        self.ensure_one()
        company = self.sudo()
        return bool(company.sms_kavenegar_enabled and company.sms_kavenegar_api_key
                    and company.sms_kavenegar_otp_template)

    def _sms_kavenegar_send_otp(self, number, code):
        """Send `code` through the approved verify/lookup template; Kavenegar gives
        these the highest priority and never filters them. Returns the message id,
        and raises KavenegarError when Kavenegar refuses or cannot be reached."""
        self.ensure_one()
        if not self._sms_kavenegar_otp_ready():
            raise KavenegarError('verify/lookup', 0, "not configured")
        entries = self._sms_kavenegar_client().verify_lookup(
            number, self.sudo().sms_kavenegar_otp_template, code) or []
        return str((entries[:1] or [{}])[0].get('messageid') or '')
