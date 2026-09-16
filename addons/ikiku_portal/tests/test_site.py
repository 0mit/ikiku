# Part of iKiKu. Licensed under AGPL-3.0.
from datetime import timedelta

from odoo import fields
from odoo.tests import HttpCase, tagged

PUBLIC_KEYS = {'position', 'province', 'date_start_fa', 'date_end_fa', 'seats'}


@tagged('post_install', '-at_install')
class TestSite(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        holder = env['res.partner'].create({'name': "دارندهٔ کافه"})
        cls.business = env['ikiku.business'].create({'name': "کافه‌ای که نامش عمومی نیست",
                                                     'partner_id': holder.id})
        cls.node = env.ref('ikiku_base.spec_dishwashing')
        position = env['ikiku.position'].create({
            'name': "عنوانِ داخلیِ ظرف‌شویِ شبِ ما", 'business_id': cls.business.id,
            'spec_node_id': cls.node.id})
        cls.tehran = env.ref('ikiku_base.province_te')
        cls.other = env['ikiku.province'].search([('id', '!=', cls.tehran.id)], limit=1)
        today = fields.Date.today()
        base = {'business_id': cls.business.id, 'position_id': position.id,
                'date_start': today + timedelta(days=30), 'date_end': today + timedelta(days=60)}
        env['ikiku.demand'].create([
            dict(base, seats=2, province_id=cls.tehran.id, state='open'),
            dict(base, seats=3, province_id=cls.other.id, state='proposed'),
            dict(base, seats=9, province_id=cls.tehran.id, state='draft'),
        ])

    def test_open_jobs_are_plain_public_values(self):
        jobs = self.env['ikiku.demand'].ikiku_public_open()
        self.assertEqual(sorted(job['seats'] for job in jobs), ['۲', '۳'])
        self.assertTrue(all(set(job) == PUBLIC_KEYS for job in jobs))
        self.assertTrue(all(job['position'] == self.node.name for job in jobs))
        self.assertEqual(self.env['ikiku.demand'].ikiku_public_open_count(), 2)

    def test_home_keeps_the_name_and_shows_open_jobs_without_the_business(self):
        page = self.url_open('/').text
        self.assertIn('آیکی؟ کو؟', page)
        self.assertIn('id="ikiku-doors"', page)
        self.assertIn(self.node.name, page)
        self.assertIn('همهٔ کارهای باز (۲)', page)
        self.assertNotIn(self.business.name, page)
        self.assertNotIn('عنوانِ داخلیِ ظرف‌شویِ شبِ ما', page)

    def test_jobs_filter_by_province(self):
        page = self.url_open('/ikiku/jobs?province=%d' % self.tehran.id).text
        self.assertIn('۲ نفر', page)
        self.assertNotIn('۳ نفر', page)
        self.assertNotIn('۹ نفر', page)
        self.assertNotIn(self.business.name, page)
        everywhere = self.url_open('/ikiku/jobs?province=nonsense')
        self.assertEqual(everywhere.status_code, 200)
        self.assertIn('۳ نفر', everywhere.text)
