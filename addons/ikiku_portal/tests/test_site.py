# Part of iKiKu. Licensed under AGPL-3.0.
from datetime import timedelta

from odoo import fields
from odoo.tests import HttpCase, tagged


def place(env, name, kind='city'):
    """A place from place_ir, by name. Tests say «تهران» and «کرج», not an xmlid nobody reads."""
    found = env['place.node'].sudo().search([('kind', '=', kind), ('name', '=', name)], limit=1)
    assert found, "place_ir has no %s called %s" % (kind, name)
    return found

PUBLIC_KEYS = {'position', 'seats', 'work_type', 'province', 'city', 'place',
               'date_start_fa', 'date_end_fa'}
# Links into the public standard (the role's page and its skills), never values of the need itself.
STANDARD_KEYS = {'position_url', 'skills', 'more_skills'}


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
        cls.tehran = place(env, "تهران")
        cls.karaj = place(env, "کرج")
        cls.tehran_province = place(env, "استان تهران", 'province')
        cls.other = cls.karaj
        today = fields.Date.today()
        base = {'business_id': cls.business.id, 'position_id': position.id,
                'date_start': today + timedelta(days=30), 'date_end': today + timedelta(days=60)}
        env['ikiku.demand'].create([
            dict(base, seats=2, place_id=cls.tehran.id, state='open'),
            dict(base, seats=3, place_id=cls.other.id, state='proposed'),
            dict(base, seats=9, place_id=cls.tehran.id, state='draft'),
        ])

    def test_open_jobs_are_plain_public_values(self):
        jobs = self.env['ikiku.demand'].ikiku_public_open()
        self.assertEqual(sorted(job['seats'] for job in jobs), ['۲', '۳'])
        self.assertTrue(all(set(job) == PUBLIC_KEYS | STANDARD_KEYS for job in jobs))
        self.assertTrue(all(job['position'] == self.node.name for job in jobs))
        self.assertEqual(self.env['ikiku.demand'].ikiku_public_open_count(), 2)

    def test_home_keeps_the_name_and_shows_open_jobs_without_the_business(self):
        page = self.url_open('/').text
        self.assertIn('آیکی؟ کو؟', page)
        self.assertIn('id="ikiku-doors"', page)
        self.assertIn(self.node.name, page)
        self.assertIn('همه‌ی کارهای باز (۲)', page)
        self.assertNotIn(self.business.name, page)
        self.assertNotIn('عنوانِ داخلیِ ظرف‌شویِ شبِ ما', page)

    def test_jobs_filter_by_province(self):
        page = self.url_open('/jobs?province=%d' % self.tehran_province.id).text
        self.assertIn('۲ نفر لازمه', page)
        self.assertNotIn('۳ نفر', page)
        self.assertNotIn('۹ نفر', page)
        self.assertNotIn(self.business.name, page)
        everywhere = self.url_open('/jobs?province=nonsense')
        self.assertEqual(everywhere.status_code, 200)
        self.assertIn('۳ نفر', everywhere.text)

    def test_the_brand_is_the_logo_and_titles_say_the_name_once(self):
        website = self.env['website'].search([], limit=1)
        company = self.env.ref('base.main_company')
        self.assertFalse(company.uses_default_logo)
        self.assertNotEqual(website.favicon, website._default_favicon())
        self.assertTrue(website.social_default_image)
        self.assertNotIn(website.name, ('My Website', 'Website'))
        home = self.url_open('/').text
        self.assertIn('ikiku-horizontal.svg', home)
        self.assertIn('rel="apple-touch-icon" href="/ikiku_portal/static/src/img/ikiku-icon-180.png"', home)
        self.assertIn('<title>آیکی؟ کو؟ | %s</title>' % website.name, home)
        for url, title in (('/ki', "کی؟"), ('/help', "راهنما"), ('/roles/waiter', "پذیرایی از مهمان")):
            page = self.url_open(url).text
            self.assertIn('<title>%s | %s</title>' % (title, website.name), page, url)
            self.assertNotIn('<title>ایکیکو —', page, url)

    def test_job_cards_link_the_role_and_its_skills_into_the_knowledge_base(self):
        jobs = self.env['ikiku.demand'].ikiku_public_open()
        job = jobs[0]
        self.assertEqual(job['position_url'], '/roles/%s' % self.node.code)
        self.assertTrue(job['skills'])
        self.assertLessEqual(len(job['skills']), 4)
        core = self.node.requirement_ids.filtered(lambda r: r.importance == 'core').mapped('skill_id')
        self.assertIn('/skills/%s' % core[0].code, [url for _label, url in job['skills']])
        for url in ('/jobs', '/'):
            page = self.url_open(url).text
            self.assertIn('href="/roles/%s"' % self.node.code, page, url)
            self.assertIn('href="/skills/', page, url)
        self.assertNotIn(self.business.name, self.url_open('/jobs').text, "still never the business")
        # A role a country rule withholds is shown by name only, with no links.
        rule = self.env['ikiku.spec.country.rule'].create({
            'node_id': self.node.id, 'country_id': self.env['ikiku.spec.node'].ikiku_country().id,
            'offered': False, 'reason': "test"})
        withheld = self.env['ikiku.demand'].ikiku_public_open()[0]
        self.assertNotIn('position_url', withheld)
        rule.unlink()

