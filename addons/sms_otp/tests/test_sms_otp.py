# Part of iKiKu. Licensed under AGPL-3.0.
from odoo.tests import TransactionCase, tagged

from odoo.addons.sms_otp.tools.otp import SmsOtpError


@tagged('post_install', '-at_install')
class TestSmsOtp(TransactionCase):

    def test_nothing_switched_on(self):
        company = self.env['res.company'].create({'name': "بی‌پیامک"})
        self.assertEqual(company._sms_providers_enabled(), [])
        self.assertFalse(company._sms_otp_ready())
        with self.assertRaises(SmsOtpError) as caught:
            company._sms_otp_send('+989121234567', '123456')
        self.assertEqual((caught.exception.status, caught.exception.bad_number), (0, False))
