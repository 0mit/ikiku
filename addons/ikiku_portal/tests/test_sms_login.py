# Part of iKiKu. Licensed under AGPL-3.0.
"""Signing in with a mobile number and an SMS code (operator, 2026-09-16: D-1 B, D-2 B,
D-3, D-7 A, D-8 C)."""
import re
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessDenied, UserError
from odoo.tests import HttpCase, tagged

from odoo.addons.ikiku_portal.tests.test_mobile_challenge import CODE, MOBILE, RANDBELOW, OtpSetup
from odoo.addons.ikiku_portal.models.mobile_challenge import MESSAGES

TOKEN = re.compile(r'name="csrf_token" value="([^"]+)"')


@tagged('post_install', '-at_install')
class TestSmsLogin(OtpSetup, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.enable_otp()

    def enter(self, mobile='۰۹۱۲۱۲۳۴۵۶۷', code='۱۲۳۴۵۶', role='ki'):
        page = self.url_open('/enter?as=%s' % role).text
        with patch(RANDBELOW, return_value=CODE):
            sent = self.url_open('/enter/send', allow_redirects=False, data={
                'csrf_token': TOKEN.search(page).group(1), 'mobile': mobile, 'role': role})
        self.assertTrue(sent.headers['Location'].endswith('/enter/code'), sent.text[:300])
        self.send_queued()
        page = self.url_open('/enter/code').text
        return self.url_open('/enter/code/submit', allow_redirects=False, data={
            'csrf_token': TOKEN.search(page).group(1), 'code': code})

    def users_with_number(self):
        return self.env['res.users'].with_context(active_test=False).search(
            [('partner_id.ikiku_mobile', '=', MOBILE)])

    def test_a_new_number_signs_up_and_is_signed_in(self):
        response = self.enter()
        self.assertTrue(response.headers['Location'].endswith('/join'))
        user = self.users_with_number()
        self.assertEqual(len(user), 1)
        self.assertTrue(user.share)
        self.assertTrue(user.login.startswith('m-'))
        self.assertNotIn('912', user.login)
        self.assertTrue(user.partner_id.ikiku_mobile_verified_on)
        again = self.url_open('/enter', allow_redirects=False)
        self.assertTrue(again.headers['Location'].endswith('/join'), "already signed in")

    def test_the_same_number_opens_the_same_account(self):
        self.enter()
        first = self.users_with_number()
        self.url_open('/web/session/logout')
        self.enter(mobile='09121234567', code='123456')
        self.assertEqual(self.users_with_number(), first)

    def test_the_last_code_still_signs_in_from_another_session(self):
        page = self.url_open('/enter?as=ki').text
        with patch(RANDBELOW, return_value=CODE):
            self.url_open('/enter/send', data={'csrf_token': TOKEN.search(page).group(1), 'mobile': MOBILE})
        self.send_queued()
        Challenge = self.env['ikiku.mobile.challenge'].sudo()
        before = Challenge.search_count([('mobile', '=', MOBILE)])
        self.opener.cookies.clear()
        page = self.url_open('/enter?as=ki').text
        again = self.url_open('/enter/send', allow_redirects=False,
                              data={'csrf_token': TOKEN.search(page).group(1), 'mobile': '09121234567'})
        self.assertTrue(again.headers['Location'].endswith('/enter/code?note=reused'))
        self.assertEqual(Challenge.search_count([('mobile', '=', MOBILE)]), before, "no new SMS")
        page = self.url_open('/enter/code?note=reused').text
        self.assertIn("آخرین کدی که براتون فرستادیم هنوز کار می‌کنه", page)
        signed_in = self.url_open('/enter/code/submit', allow_redirects=False,
                                  data={'csrf_token': TOKEN.search(page).group(1), 'code': '123456'})
        self.assertTrue(signed_in.headers['Location'].endswith('/join'))
        self.assertTrue(self.users_with_number())

    def test_a_wrong_code_does_not_sign_in(self):
        response = self.enter(code='000000')
        self.assertIn('error=wrong', response.headers['Location'])
        self.assertFalse(self.users_with_number())

    def test_a_staff_number_is_refused(self):
        staff = self.env['res.users'].create({'name': "همکار", 'login': 'staff-sms', 'password': 'staff-sms-pass-1',
                                              'group_ids': [(6, 0, [self.env.ref('base.group_user').id])]})
        staff.partner_id.write({'ikiku_mobile': MOBILE, 'ikiku_mobile_verified_on': fields.Datetime.now()})
        response = self.enter()
        self.assertIn('error=staff', response.headers['Location'])

    def test_an_unproven_typed_number_gives_way(self):
        other = self.env['res.partner'].create({'name': "تایپ‌کرده", 'ikiku_mobile': MOBILE})
        self.enter()
        self.assertFalse(other.ikiku_mobile)
        self.assertNotEqual(self.users_with_number().partner_id, other)

    def test_a_staff_created_account_is_opened_by_its_number(self):
        staff = self.env['res.users'].create({'name': "همکار", 'login': 'staff-helper', 'password': 'staff-helper-1',
                                              'group_ids': [(6, 0, [self.env.ref('base.group_user').id,
                                                                    self.env.ref('ikiku_base.group_ikiku_staff').id])]})
        wizard = self.env['ikiku.staff.account'].with_user(staff).create(
            {'name': "رضا محمدی", 'mobile': '۰۹۱۲۱۲۳۴۵۶۷', 'role': 'ki'})
        wizard.action_create()
        made = self.users_with_number()
        self.assertEqual(len(made), 1)
        self.assertFalse(made.partner_id.ikiku_mobile_verified_on)
        self.assertEqual(made.partner_id.ikiku_mobile_set_by_id, staff)
        response = self.enter()
        self.assertTrue(response.headers['Location'].endswith('/me'))
        self.assertEqual(self.users_with_number(), made)
        self.assertTrue(made.partner_id.ikiku_mobile_verified_on)

    def test_the_login_token_is_single_use_and_portal_only(self):
        Challenge = self.env['ikiku.mobile.challenge'].sudo()
        challenge = Challenge.create({'mobile': MOBILE, 'purpose': 'enter', 'session_key': 'k',
                                      'code_hash': Challenge._hash('1'), 'state': 'done'})
        user, token, error = challenge._issue_login()
        self.assertFalse(error)
        credential = {'type': 'ikiku_sms', 'login': user.login, 'token': token}
        self.assertEqual(user.with_user(user)._check_credentials(credential, {})['uid'], user.id)
        with self.assertRaises(AccessDenied):
            user.with_user(user)._check_credentials(credential, {})
        self.assertEqual(challenge._issue_login()[2], 'expired', "a challenge issues one token")
        internal = self.env.ref('base.user_admin')
        with self.assertRaises(AccessDenied):
            internal.with_user(internal)._check_credentials(
                {'type': 'ikiku_sms', 'login': internal.login, 'token': token}, {})

    def test_changing_a_number_needs_the_national_id(self):
        self.env['ir.config_parameter'].sudo().set_param('ikiku.nid_salt', 'test-salt')
        partner = self.env['res.partner'].create({'name': "مریم", 'ikiku_mobile': '+989351234567',
                                                  'ikiku_mobile_verified_on': fields.Datetime.now()})
        partner.ikiku_nid_hash = partner.hash_national_id('0012345678')
        Change = self.env['ikiku.mobile.change']
        with self.assertRaises(UserError):
            Change.create({'partner_id': partner.id, 'new_mobile': MOBILE, 'national_id': '0099999999'}).action_apply()
        change = Change.create({'partner_id': partner.id, 'new_mobile': MOBILE, 'national_id': '۰۰۱۲۳۴۵۶۷۸'})
        self.assertFalse(change.national_id)
        change.action_apply()
        self.assertEqual((partner.ikiku_mobile, partner.ikiku_mobile_verified_on), (MOBILE, False))
        self.assertEqual(partner.ikiku_mobile_set_by_id, self.env.user)

    def test_email_signup_is_closed_and_sessions_last_thirty_days(self):
        self.assertEqual(self.env['website'].search([], limit=1).auth_signup_uninvited, 'b2b')
        self.assertEqual(self.env['ir.config_parameter'].sudo().get_param('sessions.max_inactivity_seconds'),
                         str(30 * 24 * 3600))

    def test_my_sends_an_ikiku_account_home(self):
        user = self.env['res.users'].create({'name': "نیرو", 'login': 'my-walker', 'password': 'my-walker-pass-1',
                                             'group_ids': [(6, 0, [self.env.ref('base.group_portal').id])]})
        self.env['ikiku.resource'].create({'partner_id': user.partner_id.id})
        self.authenticate('my-walker', 'my-walker-pass-1')
        response = self.url_open('/my', allow_redirects=False)
        self.assertTrue(response.headers['Location'].endswith('/me'))


@tagged('post_install', '-at_install')
class TestLoginPageSms(OtpSetup, HttpCase):
    """SMS sign-in on Odoo's own /web/login (operator, 2026-09-16)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.enable_otp()

    def login_send(self, mobile='۰۹۱۲۱۲۳۴۵۶۷', redirect=None):
        page = self.url_open('/web/login' + ('?redirect=%s' % redirect if redirect else ''))
        self.assertEqual(page.status_code, 200)
        data = {'csrf_token': TOKEN.search(page.text).group(1), 'mobile': mobile, 'origin': 'login'}
        if redirect:
            data['redirect'] = redirect
        with patch(RANDBELOW, return_value=CODE):
            return self.url_open('/enter/send', allow_redirects=False, data=data)

    def submit(self, code='123456'):
        self.send_queued()
        page = self.url_open('/enter/code').text
        return self.url_open('/enter/code/submit', allow_redirects=False, data={
            'csrf_token': TOKEN.search(page).group(1), 'code': code})

    def test_the_login_page_offers_sms_and_email(self):
        page = self.url_open('/web/login').text
        self.assertIn('action="/enter/send"', page)
        self.assertIn('name="origin" value="login"', page)
        self.assertIn("یا با ایمیل و رمز", page)
        self.env.company.write({'sms_kavenegar_enabled': False})
        off = self.url_open('/web/login').text
        self.assertNotIn('action="/enter/send"', off)
        self.assertIn("ورود با پیامک الان کار نمی‌کنه", off)

    def test_signed_in_people_see_no_sms_box(self):
        self.env['res.users'].create({'name': "همکار", 'login': 'login-staff', 'password': 'login-staff-pass-1',
                                      'group_ids': [(6, 0, [self.env.ref('base.group_user').id])]})
        self.authenticate('login-staff', 'login-staff-pass-1')
        self.assertNotIn('action="/enter/send"', self.url_open('/web/login').text)

    def test_sms_from_the_login_page_signs_in_and_keeps_the_redirect(self):
        sent = self.login_send(redirect='/jobs')
        self.assertTrue(sent.headers['Location'].endswith('/enter/code'))
        self.assertIn('/web/login?redirect=%2Fjobs', self.url_open('/enter/code').text, "the back link returns")
        wrong = self.submit('111111')
        self.assertIn('error=wrong', wrong.headers['Location'])
        done = self.submit()
        self.assertTrue(done.headers['Location'].endswith('/jobs'), done.headers['Location'])
        user = self.env['res.users'].search([('partner_id.ikiku_mobile', '=', MOBILE)])
        self.assertTrue(user.share and user.login.startswith('m-'))

    def test_a_new_account_from_the_login_page_chooses_a_door(self):
        self.login_send()
        self.assertTrue(self.submit().headers['Location'].endswith('/#ikiku-doors'))

    def test_an_existing_worker_goes_home(self):
        partner = self.env['res.partner'].create({'name': "نیرو", 'ikiku_mobile': MOBILE,
                                                  'ikiku_mobile_verified_on': fields.Datetime.now()})
        partner._ikiku_grant_role('ki')
        self.login_send()
        self.assertTrue(self.submit().headers['Location'].endswith('/me'))

    def test_offsite_and_backend_redirects_are_dropped_for_portal(self):
        for target in ('//evil.example', 'https://evil.example', '/odoo/action-1'):
            with self.subTest(target=target):
                self.url_open('/web/session/logout')
                self.env['ikiku.mobile.challenge'].sudo().search([]).unlink()
                self.login_send(redirect=target)
                location = self.submit().headers['Location']
                self.assertNotIn('evil', location)
                self.assertNotIn('/odoo', location)

    def test_an_error_keeps_the_number_out_of_the_url(self):
        bad = self.login_send(mobile='0912123')
        location = bad.headers['Location']
        self.assertIn('/web/login?sms=1', location)
        self.assertNotIn('0912123', location)
        page = self.url_open(location).text
        self.assertIn('value="0912123"', page)
        self.assertIn(MESSAGES['mobile'], page)
        self.assertNotIn(MESSAGES['mobile'], self.url_open('/web/login').text, "shown once")

    def test_a_staff_number_is_refused_on_the_login_page(self):
        staff = self.env['res.users'].create({'name': "همکار", 'login': 'login-staff-2',
                                              'group_ids': [(6, 0, [self.env.ref('base.group_user').id])]})
        staff.partner_id.write({'ikiku_mobile': MOBILE, 'ikiku_mobile_verified_on': fields.Datetime.now()})
        self.login_send()
        refused = self.submit()
        self.assertIn('/web/login?sms=1', refused.headers['Location'])
        self.assertIn(MESSAGES['staff_here'], self.url_open(refused.headers['Location']).text)
        self.assertNotIn('ikiku__switch', self.url_open('/my', allow_redirects=False).text)
        self.assertEqual(self.url_open('/my', allow_redirects=False).status_code, 303, "still signed out")

    def test_a_posted_sms_credential_does_not_sign_in(self):
        Challenge = self.env['ikiku.mobile.challenge'].sudo()
        challenge = Challenge.create({'mobile': MOBILE, 'purpose': 'enter', 'session_key': 'k',
                                      'code_hash': Challenge._hash('1'), 'state': 'done'})
        user, token, _error = challenge._issue_login()
        page = self.url_open('/web/login').text
        response = self.url_open('/web/login', allow_redirects=False, data={
            'csrf_token': TOKEN.search(page).group(1), 'type': 'ikiku_sms', 'login': user.login, 'token': token})
        self.assertEqual(response.status_code, 200, "the login page again, not a redirect")

    def test_password_login_is_unchanged_and_a_number_gets_a_hint(self):
        self.env['res.users'].create({'name': "همکار", 'login': 'login-mail@example.com', 'password': 'login-mail-pass-1',
                                      'group_ids': [(6, 0, [self.env.ref('base.group_user').id])]})
        page = self.url_open('/web/login').text
        ok = self.url_open('/web/login', allow_redirects=False, data={
            'csrf_token': TOKEN.search(page).group(1), 'login': 'login-mail@example.com', 'password': 'login-mail-pass-1'})
        self.assertIn('/odoo', ok.headers['Location'])
        self.url_open('/web/session/logout')
        hints = []
        for login in ('09121234567', '09351234567'):
            page = self.url_open('/web/login').text
            wrong = self.url_open('/web/login', data={
                'csrf_token': TOKEN.search(page).group(1), 'login': login, 'password': 'nope'}).text
            hints.append(MESSAGES['login_is_mobile'] in wrong)
        self.assertEqual(hints, [True, True])

    def test_sms_sign_in_still_asks_for_two_factor(self):
        partner = self.env['res.partner'].create({'name': "نیرو", 'ikiku_mobile': MOBILE,
                                                  'ikiku_mobile_verified_on': fields.Datetime.now()})
        user = self.env['ikiku.mobile.challenge'].sudo()._portal_user_for(partner)
        with patch.object(type(self.env['res.users']), '_mfa_url', lambda self: '/web/login/totp'):
            self.login_send()
            location = self.submit().headers['Location']
        self.assertIn('/web/login/totp', location)
        self.assertTrue(user)
