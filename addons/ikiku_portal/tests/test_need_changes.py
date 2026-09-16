# Part of iKiKu. Licensed under AGPL-3.0.
"""A business changes or closes its own need (operator, 2026-09-16): every change and
closure is recorded, «found» is a different end from a cancellation, and a cancellation
needs a written reason."""
import re

from odoo.exceptions import UserError, ValidationError
from odoo.tests import HttpCase, tagged

TOKEN = re.compile(r'name="csrf_token" value="([^"]+)"')


@tagged('post_install', '-at_install')
class TestNeedChanges(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.tehran = env.ref('ikiku_base.province_te')
        cls.other_province = env['ikiku.province'].search([('id', '!=', cls.tehran.id)], limit=1)
        cls.node = env.ref('ikiku_base.spec_dishwashing')
        cls.full = env.ref('ikiku_base.work_type_full_time')
        cls.owner = env['res.users'].create({'name': "مریم", 'login': 'need-owner', 'password': 'need-owner-pass-1',
                                             'group_ids': [(6, 0, [env.ref('base.group_portal').id])]})
        cls.business = cls.owner.partner_id._ikiku_grant_role('ku', business_name="کافه نارنج")
        position = env['ikiku.position'].create({'name': "ظرف‌شور", 'business_id': cls.business.id,
                                                 'spec_node_id': cls.node.id})
        cls.need = env['ikiku.demand'].create({
            'business_id': cls.business.id, 'position_id': position.id, 'seats': 2, 'work_type_id': cls.full.id,
            'province_id': cls.tehran.id, 'city': "تهران", 'state': 'open'})
        worker = env['ikiku.resource'].create({'partner_id': env['res.partner'].create({'name': "نیرو"}).id,
                                               'state': 'active'})
        cls.availability = env['ikiku.availability'].create({'resource_id': worker.id, 'province_id': cls.tehran.id})
        cls.worker = worker
        env['ikiku.proposal'].build_for_demand(cls.need)

    def setUp(self):
        super().setUp()
        self.authenticate('need-owner', 'need-owner-pass-1')

    def post(self, url, data):
        token = TOKEN.search(self.url_open(url.split('?')[0]).text).group(1)
        return self.url_open(url, data=dict(data, csrf_token=token), allow_redirects=False)

    def location(self, response):
        self.assertIn(response.status_code, (302, 303), response.text[:300])
        return response.headers['Location']

    def test_the_page_offers_change_and_close(self):
        page = self.url_open('/business').text
        self.assertIn('/business/need/%d/edit' % self.need.id, page)
        self.assertIn('/business/need/%d/close' % self.need.id, page)
        self.assertIn('/business/need/new', page)

    def test_a_change_goes_through_the_same_questions_and_is_recorded(self):
        self.assertIn('/business/need/who', self.location(self.url_open('/business/need/%d/edit' % self.need.id,
                                                                          allow_redirects=False)))
        who = self.url_open('/business/need/who').text
        self.assertIn("دارید درخواستی رو که قبلاً ثبت کردید عوض می‌کنید", who)
        self.post('/business/need/who', {'node_id': str(self.node.id)})
        self.post('/business/need/type', {'work_type_id': str(self.full.id)})
        self.post('/business/need/count', {'seats': '3'})
        self.assertRegex(self.url_open('/business/need/when').text, r'name="end" value="none"\s+checked="checked"')
        self.post('/business/need/when', {'start': 'today', 'end': 'none'})
        where = self.url_open('/business/need/where').text
        self.assertIn('value="تهران"', where)
        self.assertIn("تغییرها رو ثبت کن", where)
        done = self.post('/business/need/where', {'province_id': str(self.other_province.id), 'city': "کرج"})
        self.assertTrue(self.location(done).endswith('/business?done=changed'))
        self.assertEqual(self.env['ikiku.demand'].search_count([('business_id', '=', self.business.id)]), 1,
                         "changed in place, not a second need")
        self.assertEqual((self.need.seats, self.need.province_id, self.need.city, self.need.state),
                         (3, self.other_province, "کرج", 'open'))
        tracked = self.need.message_ids.mapped('tracking_value_ids.field_id.name')
        self.assertIn('seats', tracked)
        self.assertIn('city', tracked)
        self.assertTrue(any("عوض شد" in body for body in self.need.message_ids.mapped('body')))
        self.assertEqual(self.need.message_ids.filtered(lambda m: "عوض شد" in m.body).author_id, self.owner.partner_id)
        self.assertFalse(self.env['ikiku.proposal'].search([('demand_id', '=', self.need.id),
                                                            ('resource_id', '=', self.worker.id)]),
                         "the old ranking went with the old place")
        self.assertIn("تغییرها ثبت شد", self.url_open('/business?done=changed').text)

    def test_a_new_need_forgets_an_unfinished_change(self):
        self.url_open('/business/need/%d/edit' % self.need.id)
        self.url_open('/business/need/new')
        self.assertNotIn("عوض می‌کنید", self.url_open('/business/need/who').text)

    def test_found_is_its_own_end(self):
        page = self.url_open('/business/need/%d/close' % self.need.id).text
        self.assertIn("نیرو پیدا کردم", page)
        self.assertIn("لغو می‌کنم", page)
        done = self.post('/business/need/%d/close' % self.need.id, {'outcome': 'found'})
        self.assertTrue(self.location(done).endswith('/business?done=filled'))
        self.assertEqual((self.need.state, self.need.closed_by_id, self.need.cancel_reason),
                         ('filled', self.owner, False))
        self.assertTrue(self.need.closed_on)
        self.assertEqual(set(self.need_proposals().mapped('state')), {'expired'})
        self.assertNotIn('/business/need/%d/edit' % self.need.id, self.url_open('/business').text)

    def need_proposals(self):
        return self.env['ikiku.proposal'].search([('demand_id', '=', self.need.id)])

    def test_a_cancellation_needs_a_written_reason(self):
        empty = self.post('/business/need/%d/cancel' % self.need.id, {'reason': '   '})
        self.assertEqual(empty.status_code, 200)
        self.assertIn("بدونِ دلیل لغو نمیشه", empty.text)
        self.assertIn(self.need.state, ('open', 'proposed'))
        done = self.post('/business/need/%d/cancel' % self.need.id, {'reason': "کافه دو هفته تعطیله"})
        self.assertTrue(self.location(done).endswith('/business?done=cancelled'))
        self.assertEqual((self.need.state, self.need.cancel_reason, self.need.closed_by_id),
                         ('cancelled', "کافه دو هفته تعطیله", self.owner))
        self.assertIn("دلیلِ لغو: کافه دو هفته تعطیله", self.url_open('/business').text)

    def test_the_rule_holds_outside_the_portal(self):
        with self.assertRaises(ValidationError):
            self.need.write({'state': 'cancelled'})
        with self.assertRaises(UserError):
            self.need.ikiku_cancel('  ')
        self.env['ikiku.demand.cancel'].create({'demand_id': self.need.id, 'reason': "staff"}).action_cancel()
        self.assertEqual(self.need.state, 'cancelled')

    def test_a_booked_need_goes_through_staff(self):
        self.env['ikiku.booking'].create({'demand_id': self.need.id, 'resource_id': self.worker.id})
        page = self.url_open('/business').text
        self.assertNotIn('/business/need/%d/edit' % self.need.id, page)
        self.assertIn('/help/tamas?from=need-%d' % self.need.id, page)
        for url in ('/business/need/%d/edit', '/business/need/%d/close', '/business/need/%d/cancel'):
            self.assertTrue(self.location(self.url_open(url % self.need.id, allow_redirects=False))
                            .endswith('/business/need/%d' % self.need.id))
        with self.assertRaises(UserError):
            self.need.ikiku_cancel("دلیل")
        self.assertIn(self.need.state, ('open', 'proposed'))

    def test_another_business_need_is_not_found(self):
        stranger = self.env['res.partner'].create({'name': "دیگری"})
        other = self.env['ikiku.business'].create({'name': "کافه دیگر", 'partner_id': stranger.id})
        position = self.env['ikiku.position'].create({'name': "x", 'business_id': other.id, 'spec_node_id': self.node.id})
        need = self.env['ikiku.demand'].create({'business_id': other.id, 'position_id': position.id,
                                                'province_id': self.tehran.id, 'state': 'open'})
        for url in ('/business/need/%d', '/business/need/%d/edit', '/business/need/%d/close'):
            self.assertEqual(self.url_open(url % need.id, allow_redirects=False).status_code, 404, url)
        self.assertEqual(self.post('/business/need/%d/cancel' % self.need.id, {'reason': ''}).status_code, 200)
        self.assertEqual(need.state, 'open')
