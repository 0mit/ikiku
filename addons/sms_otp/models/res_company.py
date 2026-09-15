# Part of iKiKu. Licensed under AGPL-3.0.
from odoo import _, models
from odoo.exceptions import ValidationError

from odoo.addons.sms_otp.tools.otp import SmsOtpError


class ResCompany(models.Model):
    _inherit = 'res.company'

    def _sms_providers_enabled(self):
        """Names of the SMS providers switched on for this company; each provider
        module adds its own."""
        self.ensure_one()
        return []

    def _sms_check_single_provider(self):
        """Called from each provider's constraint on its own switch."""
        for company in self:
            enabled = company._sms_providers_enabled()
            if len(enabled) > 1:
                raise ValidationError(_(
                    "%(company)s can send SMS through one provider at a time; switch off all but one of: "
                    "%(providers)s.", company=company.name, providers=', '.join(enabled)))

    def _sms_otp_ready(self):
        """Whether a verification code can be sent: a provider is on, with the
        key and the approved template it needs."""
        self.ensure_one()
        return False

    def _sms_otp_send(self, number, code):
        """Send `code` to `number` through the company's provider. Returns
        (provider, message id), and raises SmsOtpError when it cannot."""
        self.ensure_one()
        raise SmsOtpError('otp', 0, "no SMS provider is switched on")
