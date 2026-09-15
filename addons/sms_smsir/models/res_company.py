# Part of iKiKu. Licensed under AGPL-3.0.
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.sms_smsir.tools import smsir
from odoo.addons.sms_smsir.tools.smsir import SmsIrClient, SmsIrError, local_mobile
from odoo.addons.sms_smsir.tools.sms_api import SmsApiSmsIr


class ResCompany(models.Model):
    _inherit = 'res.company'

    sms_smsir_enabled = fields.Boolean("Send SMS via sms.ir")
    sms_smsir_api_key = fields.Char("sms.ir API key", groups='base.group_system', copy=False)
    sms_smsir_line = fields.Char("sms.ir sender line",
                                 help="The line number messages are sent from, as the sms.ir panel lists it.")
    sms_smsir_otp_template_id = fields.Integer(
        "sms.ir verification template",
        help="Id of a verification (ارسال سریع) template approved in the sms.ir panel.")
    sms_smsir_otp_parameter = fields.Char(
        "sms.ir template parameter", default='CODE',
        help="The parameter the code fills: CODE for a template written with #CODE#.")

    @api.constrains('sms_smsir_enabled')
    def _check_sms_smsir_single_provider(self):
        self._sms_check_single_provider()

    @api.constrains('sms_smsir_line')
    def _check_sms_smsir_line(self):
        for company in self:
            if company.sms_smsir_line and not company.sms_smsir_line.strip().isdecimal():
                raise ValidationError(_("The sms.ir sender line is a number, such as 30002101000000."))

    def _get_sms_api_class(self):
        self.ensure_one()
        if self.sms_smsir_enabled:
            return SmsApiSmsIr
        return super()._get_sms_api_class()

    def _sms_smsir_client(self):
        """`sms_smsir.endpoint` exists so a test can point the client at a stub."""
        self.ensure_one()
        endpoint = self.env['ir.config_parameter'].sudo().get_param('sms_smsir.endpoint')
        return SmsIrClient(self.sudo().sms_smsir_api_key, endpoint=endpoint or smsir.API_ROOT)

    def _sms_providers_enabled(self):
        return super()._sms_providers_enabled() + (['smsir'] if self.sms_smsir_enabled else [])

    def _sms_smsir_otp_parameter(self):
        """Accepted as the template shows it (#CODE#) or as the API wants it (CODE)."""
        self.ensure_one()
        return (self.sms_smsir_otp_parameter or '').strip().strip('#').strip()

    def _sms_smsir_otp_ready(self):
        self.ensure_one()
        company = self.sudo()
        return bool(company.sms_smsir_enabled and company.sms_smsir_api_key
                    and company.sms_smsir_otp_template_id and company._sms_smsir_otp_parameter())

    def _sms_smsir_send_otp(self, number, code):
        """Send `code` through the approved verification template, which sms.ir sends
        on its service lines, even to numbers that block advertising. Returns the
        message id, and raises SmsIrError when sms.ir refuses or cannot be reached."""
        self.ensure_one()
        if not self._sms_smsir_otp_ready():
            raise SmsIrError('/send/verify', 0, "not configured")
        company = self.sudo()
        data = company._sms_smsir_client().verify(
            local_mobile(number), company.sms_smsir_otp_template_id,
            {company._sms_smsir_otp_parameter(): code})
        return str((data if isinstance(data, dict) else {}).get('messageId') or '')

    def _sms_otp_ready(self):
        return self._sms_smsir_otp_ready() or super()._sms_otp_ready()

    def _sms_otp_send(self, number, code):
        if self.sudo().sms_smsir_enabled:
            return 'smsir', self._sms_smsir_send_otp(number, code)
        return super()._sms_otp_send(number, code)
