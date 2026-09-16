# Part of iKiKu. Licensed under AGPL-3.0.
"""One person may hold a business and look for work at the same time (operator, 2026-09-16)."""
import re
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import HttpCase, TransactionCase, tagged

from odoo.addons.ikiku_portal.tests.test_mobile_challenge import CODE, MOBILE, RANDBELOW, OtpSetup

TOKEN = re.compile(r'name="csrf_token" value="([^"]+)"')


class TwoSidesData:

    @classmethod
    def make_people(cls):
        env = cls.env
        cls.tehran = env.ref('ikiku_base.province_te')
        cls.alborz = env['ikiku.province'].search([('id', '!=', cls.tehran.id)], limit=1)
        cls.node = env.ref('ikiku_base.spec_dishwashing')
        portal = env.ref('base.group_portal')
        cls.person = env['res.users'].create({'name': "سارا", 'login': 'two-sides', 'password': 'two-sides-pass-1',
                                              'group_ids': [(6, 0, [portal.id])]})
        cls.person.partner_id.write({'ikiku_province_id': cls.tehran.id, 'ikiku_city': "تهران"})

    @classmethod
    def give_worker(cls, user):
        resource = user.partner_id._ikiku_grant_role('ki')
        resource.write({'state': 'active', 'name': user.name})
        return resource

    @classmethod
    def give_cafe(cls, user, name="کافه سارا"):
        return user.partner_id._ikiku_grant_role('ku', business_name=name)


@tagged('post_install', '-at_install')
class TestTwoSidesModel(TwoSidesData, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.make_people()

    def need(self, business, province=None, city="تهران"):
        position = self.env['ikiku.position'].create({'name': "ظرف‌شور", 'business_id': business.id,
                                                      'spec_node_id': self.node.id})
        return self.env['ikiku.demand'].create({'business_id': business.id, 'position_id': position.id,
                                                'province_id': (province or self.tehran).id, 'city': city,
                                                'seats': 1, 'state': 'open'})

    def test_one_account_holds_both_sides(self):
        resource = self.give_worker(self.person)
        cafe = self.give_cafe(self.person)
        self.assertTrue(self.person.has_group('ikiku_base.group_ikiku_resource'))
        self.assertTrue(self.person.has_group('ikiku_base.group_ikiku_business'))
        self.assertEqual(resource.partner_id, cafe.partner_id)
        self.assertEqual(self.person.partner_id.user_ids, self.person, "no second user")

    def test_a_staff_account_gets_no_side(self):
        staff = self.env['res.users'].create({'name': "همکار", 'login': 'two-staff',
                                              'group_ids': [(6, 0, [self.env.ref('base.group_user').id])]})
        with self.assertRaises(UserError):
            staff.partner_id._ikiku_grant_role('ki')
        self.assertFalse(self.env['ikiku.resource'].search([('partner_id', '=', staff.partner_id.id)]))

    def test_business_location_is_its_own(self):
        cafe = self.give_cafe(self.person)
        cafe.write({'province_id': self.tehran.id, 'city': "تهران"})
        self.person.partner_id.write({'ikiku_province_id': self.alborz.id, 'ikiku_city': "کرج"})
        self.assertEqual((cafe.province_id, cafe.city), (self.tehran, "تهران"))
        cafe.write({'city': "ری"})
        self.assertEqual(self.person.partner_id.ikiku_city, "کرج")

    def test_holder_not_ranked_for_own_business(self):
        resource = self.give_worker(self.person)
        self.env['ikiku.availability'].create({'resource_id': resource.id, 'province_id': self.tehran.id})
        own = self.need(self.give_cafe(self.person))
        other_partner = self.env['res.partner'].create({'name': "کافه‌دار"})
        other = self.need(self.env['ikiku.business'].create({'name': "کافه دیگر", 'partner_id': other_partner.id}))
        stranger = self.env['ikiku.resource'].create({
            'partner_id': self.env['res.partner'].create({'name': "غریبه"}).id, 'state': 'active'})
        self.env['ikiku.availability'].create({'resource_id': stranger.id, 'province_id': self.tehran.id})
        own_ranked = self.env['ikiku.proposal'].build_for_demand(own).mapped('resource_id')
        self.assertNotIn(resource, own_ranked)
        self.assertIn(stranger, own_ranked)
        self.assertIn(resource, self.env['ikiku.proposal'].build_for_demand(other).mapped('resource_id'))

    def test_no_booking_at_own_business(self):
        resource = self.give_worker(self.person)
        own = self.need(self.give_cafe(self.person))
        with self.assertRaises(ValidationError):
            self.env['ikiku.booking'].create({'demand_id': own.id, 'resource_id': resource.id})

    def test_old_own_bookings_are_flagged_not_cancelled(self):
        resource = self.give_worker(self.person)
        own = self.need(self.give_cafe(self.person))
        stranger = self.env['ikiku.resource'].create({'partner_id': self.env['res.partner'].create({'name': "غریبه"}).id})
        booking = self.env['ikiku.booking'].create({'demand_id': own.id, 'resource_id': stranger.id})
        # As a booking made before the rule: the constraint is bypassed the way old data was.
        self.env.cr.execute("UPDATE ikiku_booking SET resource_id = %s WHERE id = %s", [resource.id, booking.id])
        self.env.invalidate_all()
        flagged = self.env['ikiku.booking']._ikiku_flag_own_bookings()
        self.assertEqual(flagged, booking)
        self.assertEqual(booking.state, 'confirmed')
        self.assertIn("پیش از قاعدهٔ منعِ آن", booking.message_ids[0].body)

    def test_location_migration(self):
        # A holder with no worker record keeps a staff-typed place.
        lone_partner = self.env['res.partner'].create({'name': "تنها", 'ikiku_province_id': self.tehran.id})
        lone = self.env['ikiku.business'].create({'name': "تنها", 'partner_id': lone_partner.id,
                                                  'province_id': self.tehran.id, 'city': "تهران"})
        self.need(lone, province=self.alborz, city="کرج")
        # A dual holder whose café sat at their home while its need is elsewhere is moved.
        self.give_worker(self.person)
        dual = self.give_cafe(self.person)
        dual.write({'province_id': self.tehran.id, 'city': "تهران"})
        self.need(dual, province=self.alborz, city="کرج")
        # A business with no place learns it from its latest need.
        empty = self.env['ikiku.business'].create({'name': "خالی", 'partner_id': self.env['res.partner'].create(
            {'name': "خالی"}).id})
        self.need(empty, province=self.alborz, city="کرج")
        filled, detached = self.env['ikiku.business']._ikiku_place_from_needs()
        self.assertEqual((filled, detached), (1, 1))
        self.assertEqual((lone.province_id, lone.city), (self.tehran, "تهران"))
        self.assertEqual((dual.province_id, dual.city), (self.alborz, "کرج"))
        self.assertIn("آخرین اعلامِ نیاز", dual.message_ids[0].body)
        self.assertEqual((empty.province_id, empty.city), (self.alborz, "کرج"))

    def test_staff_give_a_second_side(self):
        staff = self.env['res.users'].create({'name': "همکار", 'login': 'two-helper',
                                              'group_ids': [(6, 0, [self.env.ref('base.group_user').id,
                                                                    self.env.ref('ikiku_base.group_ikiku_staff').id])]})
        self.person.partner_id.sudo().write({'ikiku_mobile': MOBILE})
        self.give_worker(self.person)
        Role = self.env['ikiku.staff.role'].with_user(staff)
        Role.create({'partner_id': self.person.partner_id.id, 'role': 'ku', 'business_name': "کافه"}).action_apply()
        self.assertTrue(self.env['ikiku.business'].search([('partner_id', '=', self.person.partner_id.id)]))
        self.assertTrue(self.person.has_group('ikiku_base.group_ikiku_business'))
        with self.assertRaises(UserError):
            Role.create({'partner_id': self.person.partner_id.id, 'role': 'ku'}).action_apply()
        both = self.env['ikiku.staff.account'].with_user(staff).create(
            {'name': "دو نقشه", 'mobile': '09351234567', 'role': 'both', 'business_name': "کافه دو"})
        both.action_create()
        partner = self.env['res.partner'].search([('ikiku_mobile', '=', '+989351234567')])
        self.assertTrue(self.env['ikiku.resource'].search([('partner_id', '=', partner.id)]))
        self.assertTrue(self.env['ikiku.business'].search([('partner_id', '=', partner.id)]))
        bodies = ' '.join(partner.message_ids.mapped('body') + self.person.partner_id.message_ids.mapped('body'))
        self.assertNotIn('9351234567', bodies)
        self.assertNotIn('9121234567', bodies)


@tagged('post_install', '-at_install')
class TestTwoSidesPages(TwoSidesData, OtpSetup, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.make_people()

    def post(self, url, data):
        token = TOKEN.search(self.url_open(url.split('?')[0]).text).group(1)
        return self.url_open(url, data=dict(data, csrf_token=token), allow_redirects=False)

    def location(self, response):
        self.assertIn(response.status_code, (301, 302, 303), response.text[:300])
        return response.headers['Location']

    def test_a_worker_adds_a_cafe(self):
        self.give_worker(self.person)
        self.authenticate('two-sides', 'two-sides-pass-1')
        door = self.url_open('/ku', allow_redirects=False)
        self.assertEqual(door.status_code, 200)
        self.assertIn("کافه یا رستوران دارید و همکار می‌خواید؟", door.text)
        self.assertFalse(self.env['ikiku.business'].search([('partner_id', '=', self.person.partner_id.id)]))
        name_page = self.url_open('/business/name').text
        self.assertIn("صفحه‌ی کاری‌تون سرِ جاشه", name_page)
        self.assertTrue(self.location(self.post('/business/name', {'name': "کافه سارا"})).endswith('/business/need/who'))
        self.assertTrue(self.person.has_group('ikiku_base.group_ikiku_business'))
        for url in ('/me', '/business'):
            self.assertIn('ikiku__switch', self.url_open(url).text, url)
        self.assertTrue(self.location(self.url_open('/ki', allow_redirects=False)).endswith('/me'))
        self.assertTrue(self.location(self.url_open('/ku', allow_redirects=False)).endswith('/business'))

    def test_an_owner_adds_work(self):
        self.give_cafe(self.person)
        self.authenticate('two-sides', 'two-sides-pass-1')
        door = self.url_open('/ki', allow_redirects=False)
        self.assertEqual(door.status_code, 200)
        self.assertIn("خودتون هم دنبالِ کار هستید؟", door.text)
        self.assertFalse(self.env['ikiku.resource'].search([('partner_id', '=', self.person.partner_id.id)]))
        self.assertIn('/join/', self.location(self.url_open('/join', allow_redirects=False)))
        self.assertTrue(self.env['ikiku.resource'].search([('partner_id', '=', self.person.partner_id.id)]))

    def test_the_chooser_and_the_remembered_side(self):
        self.give_worker(self.person)
        self.give_cafe(self.person)
        self.authenticate('two-sides', 'two-sides-pass-1')
        chooser = self.url_open('/my', allow_redirects=False)
        self.assertEqual(chooser.status_code, 200)
        self.assertIn("امروز برای چی اومدید؟", chooser.text)
        self.url_open('/business')
        self.assertTrue(self.location(self.url_open('/my', allow_redirects=False)).endswith('/business'))
        self.url_open('/me')
        self.assertTrue(self.location(self.url_open('/my', allow_redirects=False)).endswith('/me'))

    def test_one_side_goes_straight_home(self):
        self.give_cafe(self.person)
        self.authenticate('two-sides', 'two-sides-pass-1')
        self.assertTrue(self.location(self.url_open('/my', allow_redirects=False)).endswith('/business'))

    def test_moving_home_does_not_move_the_cafe(self):
        self.give_worker(self.person)
        cafe = self.give_cafe(self.person)
        cafe.write({'province_id': self.tehran.id, 'city': "تهران"})
        self.authenticate('two-sides', 'two-sides-pass-1')
        page = self.url_open('/join/where?edit=1').text
        self.assertIn("شهرِ مجموعه‌تون عوض نمیشه", page)
        self.post('/join/where?edit=1', {'province_id': str(self.alborz.id), 'city': "کرج", 'edit': '1'})
        self.assertEqual(self.person.partner_id.ikiku_city, "کرج")
        self.assertEqual((cafe.province_id, cafe.city), (self.tehran, "تهران"))

    def test_signing_in_honours_a_named_door(self):
        self.enable_otp()
        self.person.partner_id.sudo().write({'ikiku_mobile': MOBILE, 'ikiku_mobile_verified_on': fields.Datetime.now()})
        self.give_worker(self.person)

        def enter(query):
            page = self.url_open('/enter' + query).text
            data = {'csrf_token': TOKEN.search(page).group(1), 'mobile': '09121234567'}
            if 'as=' in query:
                data['role'] = query.split('as=')[1]
            with patch(RANDBELOW, return_value=CODE):
                self.url_open('/enter/send', data=data, allow_redirects=False)
            self.send_queued()
            page = self.url_open('/enter/code').text
            done = self.url_open('/enter/code/submit', allow_redirects=False,
                                 data={'csrf_token': TOKEN.search(page).group(1), 'code': str(CODE)})
            where = self.location(done)
            self.url_open('/web/session/logout')
            # The next sign-in may not wait out the minute between codes.
            self.env['ikiku.mobile.challenge'].sudo().search([('mobile', '=', MOBILE)]).unlink()
            return where

        self.assertTrue(enter('?as=ku').endswith('/ku'), "a worker at the café door is asked first")
        self.assertTrue(enter('').endswith('/me'))
        self.give_cafe(self.person)
        self.assertTrue(enter('?as=ku').endswith('/business'))

    def test_staff_are_sent_to_the_backend(self):
        self.env['res.users'].create({'name': "همکار", 'login': 'two-staff-web', 'password': 'two-staff-web-1',
                                      'group_ids': [(6, 0, [self.env.ref('base.group_user').id])]})
        self.authenticate('two-staff-web', 'two-staff-web-1')
        for url in ('/join', '/ki', '/ku', '/business/name'):
            self.assertIn('/odoo', self.location(self.url_open(url, allow_redirects=False)), url)
        self.assertFalse(self.env['ikiku.resource'].search([('partner_id.user_ids.login', '=', 'two-staff-web')]))

    def test_the_header_goes_to_my(self):
        self.give_worker(self.person)
        self.authenticate('two-sides', 'two-sides-pass-1')
        self.assertIn('href="/my"', self.url_open('/help').text)

    def test_help_explains_both_sides(self):
        self.assertEqual(self.url_open('/help/hardo').status_code, 200)
        for url in ('/help', '/help/kar', '/help/niroo'):
            self.assertIn('/help/hardo', self.url_open(url).text, url)
        dide = self.url_open('/help/dide').text
        self.assertIn("اینکه کافه یا رستوران مالِ کیه", dide)
