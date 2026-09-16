# Part of iKiKu. Licensed under AGPL-3.0.
"""The plain-words redesign, walked as a person would: one question per screen, errors
beside the field, help pages whose numbers come from the code, and old addresses kept."""
import re
from unittest.mock import patch

from odoo.tests import HttpCase, tagged

from odoo.addons.ikiku_portal.controllers import help as help_controller

TOKEN = re.compile(r'name="csrf_token" value="([^"]+)"')


@tagged('post_install', '-at_install')
class TestFlows(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        portal = cls.env.ref('base.group_portal')
        cls.worker = cls.env['res.users'].create({'name': "رضا محمدی", 'login': 'flow-worker',
                                                  'password': 'flow-worker-pass-1', 'group_ids': [(6, 0, [portal.id])]})
        cls.owner = cls.env['res.users'].create({'name': "مریم", 'login': 'flow-owner',
                                                 'password': 'flow-owner-pass-1', 'group_ids': [(6, 0, [portal.id])]})
        cls.tehran = cls.env.ref('ikiku_base.province_te')
        cls.full = cls.env.ref('ikiku_base.work_type_full_time')
        cls.shift = cls.env.ref('ikiku_base.work_type_per_shift')

    def post(self, url, data):
        token = TOKEN.search(self.url_open(url.split('?')[0]).text).group(1)
        body = [('csrf_token', token)] + (list(data.items()) if isinstance(data, dict) else data)
        return self.url_open(url, data=body, allow_redirects=False)

    def goes_to(self, response, path):
        self.assertEqual(response.status_code, 303, response.text[:400])
        self.assertTrue(response.headers['Location'].endswith(path), response.headers['Location'])

    def test_a_worker_answers_one_question_per_screen(self):
        self.authenticate('flow-worker', 'flow-worker-pass-1')
        self.goes_to(self.url_open('/join', allow_redirects=False), '/join/where')
        where = self.post('/join/where', {'city': "کرج"})
        self.assertEqual(where.status_code, 200)
        self.assertIn("استان رو انتخاب نکردید.", where.text)
        self.assertIn('value="کرج"', where.text, "what was typed stays")
        self.goes_to(self.post('/join/where', {'province_id': str(self.tehran.id), 'city': "کرج"}), '/join/skills')
        tiles = self.url_open('/join/skills').text
        self.assertIn("ظرف‌شستن", tiles)
        self.assertNotIn("شیفت صبح", tiles, "shifts are not skills")
        dishwashing = self.env.ref('ikiku_base.spec_dishwashing')
        prep = self.env.ref('ikiku_base.spec_prep')
        self.assertIn("حداقل یه کار", self.post('/join/skills', {}).text)
        self.goes_to(self.post('/join/skills', [('node_id', str(dishwashing.id)), ('node_id', str(prep.id))]), '/join/when')
        bad = self.post('/join/when', {'start': 'custom', 'start_day': '۳۱', 'start_month': '7', 'start_year': '1405',
                                       'end': 'none'})
        self.assertIn("این ماه این‌قدر روز نداره", bad.text)
        self.assertIn("حداقل", self.post('/join/when', {'start': 'today'}).text.replace("بگید تا کِی", "حداقل"))
        self.goes_to(self.post('/join/when', {'start': 'today', 'end': 'none'}), '/join/how')
        self.assertIn("یکی رو انتخاب کنید.", self.post('/join/how', {'relocate': 'no'}).text)
        self.goes_to(self.post('/join/how', [('work_type_id', str(self.full.id)), ('work_type_id', str(self.shift.id)),
                                             ('relocate', 'no')]), '/me')
        resource = self.env['ikiku.resource'].search([('partner_id', '=', self.worker.partner_id.id)])
        availability = resource.availability_ids
        self.assertEqual(resource.state, 'submitted')
        self.assertEqual((availability.date_end, set(availability.work_type_ids.ids), availability.details_confirmed),
                         (False, {self.full.id, self.shift.id}, True))
        me = self.url_open('/me').text
        self.assertIn("ثبت شد. همکارای ایکیکو نگاهش می‌کنن", me)
        self.assertIn("بدون پایان", me)
        self.goes_to(self.post('/join/where?edit=1', {'province_id': str(self.tehran.id), 'city': "تهران",
                                                      'edit': '1'}), '/me')

    def test_a_business_asks_for_people_in_five_taps(self):
        self.authenticate('flow-owner', 'flow-owner-pass-1')
        self.goes_to(self.url_open('/business', allow_redirects=False), '/business/name')
        self.goes_to(self.post('/business/name', {'name': "کافه نارنج"}), '/business/need/who')
        waiter = self.env.ref('ikiku_base.spec_waiter')
        self.assertIn("یکی رو انتخاب کنید.", self.post('/business/need/who', {}).text)
        self.url_open('/ku?node=%d' % waiter.id)
        self.assertRegex(self.url_open('/business/need/who').text,
                         r'value="%d"\s+checked="checked"|checked="checked"[^>]*value="%d"' % (waiter.id, waiter.id))
        self.goes_to(self.post('/business/need/who', {'node_id': str(waiter.id)}), '/business/need/type')
        self.goes_to(self.post('/business/need/type', {'work_type_id': str(self.shift.id)}), '/business/need/count')
        more = self.post('/business/need/count', {'seats': '۱', 'adjust': '1'})
        self.assertIn('value="۲"', more.text)
        self.goes_to(self.post('/business/need/count', {'seats': '۲', 'next': '1'}), '/business/need/when')
        self.goes_to(self.post('/business/need/when', {'start': 'week', 'end': '1m'}), '/business/need/where')
        check = self.url_open('/business/need/where').text
        self.assertIn("گارسونی", check)
        self.assertIn("اسمِ کافه‌تون دیده نمیشه", check)
        saved = self.post('/business/need/where', {'province_id': str(self.tehran.id), 'city': "تهران"})
        demand = self.env['ikiku.demand'].search([('business_id.name', '=', "کافه نارنج")])
        self.goes_to(saved, '/business/need/%d' % demand.id)
        self.assertEqual((demand.seats, demand.work_type_id, demand.city, demand.state), (2, self.shift, "تهران", 'open'))
        self.assertTrue(demand.date_end and demand.date_end > demand.date_start)
        self.assertIn("درخواستتون ثبت شد", self.url_open('/business/need/%d' % demand.id).text)
        self.assertIn("گارسونی", self.url_open('/business').text)

    def test_help_pages_read_their_numbers_from_the_code(self):
        for page in help_controller.PAGES:
            self.assertEqual(self.url_open('/help/%s' % page).status_code, 200, page)
        self.assertEqual(self.url_open('/help/nothing').status_code, 404)
        with patch('odoo.addons.ikiku_portal.models.mobile_challenge.MAX_SENDS_PER_HOUR', 7):
            self.assertIn("فقط ۷ بار", self.url_open('/help/code').text)
        dide = self.url_open('/help/dide').text
        self.assertIn("اسمتون", dide.split("فقط همکارای ایکیکو می‌بینن")[0])
        self.assertIn("کدِ ملی", dide.split("فقط همکارای ایکیکو می‌بینن")[1])
        self.assertIn("تا ۳", self.url_open('/help/etebar').text)

    def test_a_call_back_request(self):
        self.post('/help/tamas', {'name': "رضا", 'mobile': '09121234567', 'best_time': 'noon', 'website_url': 'x'})
        self.assertFalse(self.env['ikiku.help.request'].search([]), "a filled trap is not a person")
        bad = self.post('/help/tamas', {'name': "رضا", 'mobile': '123', 'best_time': 'noon'})
        self.assertIn("این شماره درست نیست", bad.text)
        self.goes_to(self.post('/help/tamas', {'name': "رضا", 'mobile': '۰۹۱۲۱۲۳۴۵۶۷', 'best_time': 'noon',
                                               'from_page': 'code'}), '/help/tamas?sent=1')
        request = self.env['ikiku.help.request'].search([])
        self.assertEqual((request.mobile, request.best_time, request.state), ('+989121234567', 'noon', 'new'))

    def test_home_has_role_shortcuts_and_cities_are_suggested(self):
        home = self.url_open('/').text
        self.assertIn('/ku?node=%d' % self.env.ref('ikiku_base.spec_waiter').id, home)
        self.authenticate('flow-worker', 'flow-worker-pass-1')
        self.url_open('/join')
        self.assertIn('<datalist id="ikiku-cities">', self.url_open('/join/where').text)
        self.assertIn('value="تهران"', self.url_open('/join/where').text)

    def test_old_addresses_move_permanently(self):
        response = self.url_open('/ikiku/jobs?province=5', allow_redirects=False)
        self.assertEqual(response.status_code, 301)
        self.assertTrue(response.headers['Location'].endswith('/jobs?province=5'))
        self.assertTrue(self.url_open('/ikiku/join/availability', allow_redirects=False).headers['Location'].endswith('/join/when'))
        self.assertTrue(self.url_open('/ikiku/ki', allow_redirects=False).headers['Location'].endswith('/ki'))
        self.assertEqual(self.url_open('/ki').status_code, 200)

    def test_the_menu_uses_the_short_addresses(self):
        urls = self.env['website'].search([], limit=1).menu_id.child_id.mapped('url')
        self.assertIn('/ki', urls)
        self.assertIn('/help', urls)
        self.assertFalse([url for url in urls if url.startswith('/ikiku')])
