# Part of iKiKu. Licensed under AGPL-3.0.
import re
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import HttpCase, TransactionCase, tagged

from odoo.addons.sms_kavenegar.tools.kavenegar import KavenegarError

CODE = 123456
MOBILE = '+989121234567'
RANDBELOW = 'odoo.addons.ikiku_portal.models.mobile_challenge.secrets.randbelow'


class OtpSetup:

    @classmethod
    def enable_otp(cls):
        cls.env.company.write({'sms_kavenegar_enabled': True, 'sms_kavenegar_api_key': 'KEY',
                               'sms_kavenegar_sender': '10004346', 'sms_kavenegar_otp_template': 'ikiku-otp'})

    def send_queued(self, result='77'):
        company_class = type(self.env['res.company'])
        options = {'side_effect': result} if isinstance(result, Exception) else {'return_value': result}
        with patch.object(company_class, '_sms_kavenegar_send_otp', **options) as send:
            self.env['ikiku.mobile.challenge']._cron_send()
        return send


@tagged('post_install', '-at_install')
class TestMobileChallenge(OtpSetup, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.enable_otp()
        cls.Challenge = cls.env['ikiku.mobile.challenge']
        cls.partner = cls.env['res.partner'].create({'name': "نیرو"})
        cls.other = cls.env['res.partner'].create({'name': "دیگری"})

    def start(self, partner=None, mobile=MOBILE):
        with patch(RANDBELOW, return_value=CODE):
            return self.Challenge.start(partner or self.partner, mobile)

    def test_code_is_sent_then_forgotten(self):
        challenge, error = self.start()
        self.assertFalse(error)
        self.assertEqual((challenge.state, challenge.pending_code), ('queued', '123456'))
        self.assertNotIn('123456', challenge.code_hash)
        self.assertFalse(self.partner.ikiku_mobile, "the number waits for its proof")
        send = self.send_queued()
        send.assert_called_once_with(MOBILE, '123456')
        self.assertEqual((challenge.state, challenge.pending_code, challenge.kavenegar_messageid), ('sent', False, '77'))

    def test_wrong_then_right_in_persian_digits(self):
        challenge, _error = self.start()
        self.send_queued()
        self.assertEqual(challenge.check('000000'), 'wrong')
        self.assertFalse(challenge.check('۱۲۳۴۵۶'))
        self.assertEqual(challenge.state, 'done')
        self.assertEqual(self.partner.ikiku_mobile, MOBILE)
        self.assertTrue(self.partner.ikiku_mobile_verified_on)

    def test_five_tries(self):
        challenge, _error = self.start()
        self.send_queued()
        self.assertEqual([challenge.check('000000') for _i in range(5)], ['wrong'] * 4 + ['tries'])
        self.assertEqual(challenge.check('123456'), 'expired')
        self.assertFalse(self.partner.ikiku_mobile)

    def test_code_runs_out(self):
        challenge, _error = self.start()
        self.send_queued()
        challenge.expires_at = fields.Datetime.now() - timedelta(seconds=1)
        self.assertEqual(challenge.check('123456'), 'expired')

    def test_wait_is_capped(self):
        challenge, _error = self.start()
        challenge.queued_at = fields.Datetime.now() - timedelta(minutes=3)
        payload = challenge._payload()
        self.assertEqual((payload['state'], challenge.failure, challenge.pending_code), ('failed', 'timeout', False))

    def test_resend_waits_a_minute(self):
        first, _error = self.start()
        again, error = self.start()
        self.assertEqual((again, error), (first, False))
        first.queued_at = fields.Datetime.now() - timedelta(seconds=61)
        fresh, _error = self.start()
        self.assertNotEqual(fresh, first)
        self.assertEqual(first.state, 'expired')

    def test_three_codes_an_hour_per_number(self):
        for name in ("الف", "ب", "پ"):
            _challenge, error = self.start(self.env['res.partner'].create({'name': name}))
            self.assertFalse(error)
        _challenge, error = self.start(self.env['res.partner'].create({'name': "ت"}))
        self.assertEqual(error, 'limit')

    def test_proven_owner_takes_an_unproven_claim(self):
        self.other.ikiku_mobile = MOBILE
        challenge, _error = self.start()
        self.send_queued()
        self.assertFalse(challenge.check('123456'))
        self.assertFalse(self.other.ikiku_mobile)
        self.assertEqual(self.partner.ikiku_mobile, MOBILE)

    def test_a_proven_number_is_not_taken(self):
        self.other.write({'ikiku_mobile': MOBILE, 'ikiku_mobile_verified_on': fields.Datetime.now()})
        _challenge, error = self.start()
        self.assertEqual(error, 'taken')

    def test_refused_number(self):
        challenge, _error = self.start()
        self.send_queued(KavenegarError('verify/lookup', 411, "receptor"))
        self.assertEqual((challenge.state, challenge.failure), ('failed', 'number'))
        self.assertEqual(challenge.check('123456'), 'number')

    def test_hand_edit_drops_the_proof(self):
        self.partner.write({'ikiku_mobile': MOBILE, 'ikiku_mobile_verified_on': fields.Datetime.now()})
        self.partner.write({'ikiku_mobile': MOBILE})
        self.assertTrue(self.partner.ikiku_mobile_verified_on)
        self.partner.write({'ikiku_mobile': '+989351234567'})
        self.assertFalse(self.partner.ikiku_mobile_verified_on)


@tagged('post_install', '-at_install')
class TestJoinWithOtp(OtpSetup, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env['res.users'].create({
            'name': "نیروی آزمایشی", 'login': 'otp-walker', 'password': 'otp-walker-pass-1',
            'group_ids': [(6, 0, [cls.env.ref('base.group_portal').id])],
        })
        cls.province = cls.env.ref('ikiku_base.province_te')

    def submit_intake(self):
        page = self.url_open('/ikiku/join').text
        token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
        return self.url_open('/ikiku/join/submit', allow_redirects=False, data={
            'csrf_token': token, 'mobile': '09121234567', 'headline': "باریستا",
            'province_id': self.province.id, 'city': "تهران"})

    def test_join_waits_for_the_code(self):
        self.enable_otp()
        self.authenticate('otp-walker', 'otp-walker-pass-1')
        with patch(RANDBELOW, return_value=CODE):
            response = self.submit_intake()
        self.assertTrue(response.headers['Location'].endswith('/ikiku/join/verify'))
        self.env.invalidate_all()
        self.assertFalse(self.user.partner_id.ikiku_mobile)
        self.assertEqual(self.url_open('/ikiku/join/verify/state').json()['state'], 'queued')
        page = self.url_open('/ikiku/join/verify').text
        self.assertIn('id="ikiku-otp"', page)
        self.send_queued()
        self.assertEqual(self.url_open('/ikiku/join/verify/state').json()['state'], 'sent')
        token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
        wrong = self.url_open('/ikiku/join/verify/submit', allow_redirects=False,
                              data={'csrf_token': token, 'code': '111111'})
        self.assertIn('error=wrong', wrong.headers['Location'])
        right = self.url_open('/ikiku/join/verify/submit', allow_redirects=False,
                              data={'csrf_token': token, 'code': '123456'})
        self.assertTrue(right.headers['Location'].endswith('/ikiku/join/skills'))
        self.env.invalidate_all()
        self.assertEqual(self.user.partner_id.ikiku_mobile, MOBILE)
        self.assertTrue(self.user.partner_id.ikiku_mobile_verified_on)

    def test_without_sms_the_number_is_written_unproven(self):
        self.authenticate('otp-walker', 'otp-walker-pass-1')
        response = self.submit_intake()
        self.assertTrue(response.headers['Location'].endswith('/ikiku/join/skills'))
        self.env.invalidate_all()
        self.assertEqual(self.user.partner_id.ikiku_mobile, MOBILE)
        self.assertFalse(self.user.partner_id.ikiku_mobile_verified_on)
