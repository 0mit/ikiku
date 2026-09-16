# Part of iKiKu. Licensed under AGPL-3.0.
"""The standard (operator, 2026-09-17): roles and the skills they need, links to ISCED-F 2013
and ISCO-08, country rules, search as people type, and the public pages that show it."""
from odoo.tests import HttpCase, tagged

BANNED = ('گارسون', 'کارگر', 'مغازه', 'خدمتکار', 'مستخدم', 'پادو', 'پیشخدمت', 'کافی‌من', 'کمک‌آشپز')


@tagged('post_install', '-at_install')
class TestStandard(HttpCase):

    def node(self, code):
        return self.env['ikiku.spec.node'].with_context(active_test=False).search([('code', '=', code)])

    def test_existing_codes_keep_their_meaning(self):
        for code in ('dishwashing', 'prep', 'line-cook', 'chef', 'barista', 'waiter', 'host', 'cashier'):
            self.assertEqual(self.node(code).kind, 'role', code)
        for code in ('espresso', 'latte-art', 'brewbar'):
            self.assertEqual(self.node(code).kind, 'competency', code)
        self.assertEqual((self.node('waiter').name, self.node('waiter').plain_label), ("میزبان", "پذیرایی از مهمان"))
        self.assertEqual(self.node('host').name, "خوشامدگو")
        self.assertEqual(self.node('dishwashing').plain_label, "شست‌وشوی ظرف")
        self.assertIn("گارسون", self.node('waiter').hint_terms, "the old word still finds the role")

    def test_every_role_has_skills_and_an_occupation(self):
        roles = self.env['ikiku.spec.node'].search([('kind', '=', 'role')])
        self.assertGreater(len(roles), 250)
        self.assertFalse(roles.filtered(lambda r: not r.requirement_ids), "a role with no skills")
        self.assertFalse(roles.filtered(lambda r: not r.knowledge_link_ids.filtered(
            lambda link: link.relation == 'classified_as')), "a role with no ISCO-08 occupation")
        self.assertEqual(self.env['ikiku.knowledge.class'].search_count([('scheme_id.code', '=', 'isco-08')]), 619)
        self.assertEqual(self.env['ikiku.knowledge.class'].search_count([('scheme_id.code', '=', 'isced-f-2013')]), 219)

    def test_a_skill_rests_on_knowledge_from_other_domains(self):
        fields = self.node('espresso').knowledge_link_ids.filtered(lambda link: link.relation == 'draws_on').mapped('class_id.code')
        self.assertIn('0533', fields, "physics: water pressure")
        self.assertIn('0713', fields, "electricity: the machine")
        self.assertIn(self.node('barista'), self.node('espresso').used_by_ids.mapped('role_id'))

    def test_names_are_respectful(self):
        nodes = self.env['ikiku.spec.node'].with_context(active_test=False).search([])
        for node in nodes:
            for word in BANNED:
                self.assertNotIn(word, node.name or '', node.code)
                self.assertNotIn(word, node.plain_label or '', node.code)

    def test_country_rules_hide_without_deleting(self):
        Node = self.env['ikiku.spec.node']
        hidden = set(Node.ikiku_hidden_ids(self.env.ref('base.ir')))
        self.assertIn(self.node('bartender').id, hidden)
        self.assertIn(self.node('cocktail-mixology').id, hidden, "the rule covers the skill family too")
        self.assertTrue(self.node('bartender').active, "kept in the tables")
        self.assertNotIn(self.node('hookah-attendant').id, hidden, "the operator chose to show it")
        self.assertFalse(Node.ikiku_hidden_ids(self.env.ref('base.fr')), "no rule elsewhere")
        rule = self.env['ikiku.spec.country.rule'].create({
            'node_id': self.node('bartender').id, 'country_id': self.env.ref('base.ir').id,
            'offered': True, 'reason': "test"})
        self.assertNotIn(self.node('bartender').id, Node.ikiku_hidden_ids(self.env.ref('base.ir')))
        rule.unlink()

    def test_search_finds_what_people_type(self):
        Node = self.env['ikiku.spec.node']
        first = lambda text: Node.resolve_text(text, kinds=('role',))[:1].code
        self.assertEqual(first("گارسون"), 'waiter')
        self.assertEqual(first("باریسته"), 'barista')
        self.assertEqual(first("کبابپز"), 'kebab-cook')
        self.assertEqual(first("كباب پز"), 'kebab-cook')
        self.assertNotIn(self.node('bartender'), Node.resolve_text("بارتندر", kinds=('role',)))
        self.assertTrue(self.node('waiter').suggest_index)

    def test_public_pages(self):
        roles = self.url_open('/roles').text
        self.assertIn("پذیرایی از مهمان", roles)
        self.assertNotIn('/roles/bartender', roles)
        self.assertIn("غذای ایرانی", roles, "long families are grouped by sub-family")
        waiter = self.url_open('/roles/waiter')
        self.assertEqual(waiter.status_code, 200)
        self.assertIn("میزبان", waiter.text)
        self.assertIn('/skills/', waiter.text)
        self.assertIn('/knowledge/isco-08/5131', waiter.text)
        self.assertEqual(self.url_open('/roles/bartender').status_code, 404)
        self.assertEqual(self.url_open('/roles/espresso').status_code, 404, "a skill is not a role")
        espresso = self.url_open('/skills/espresso').text
        self.assertIn('/knowledge/isced-f-2013/0533', espresso)
        self.assertIn('/roles/barista', espresso)
        self.assertEqual(self.url_open('/knowledge').status_code, 200)
        physics = self.url_open('/knowledge/isced-f-2013/0533').text
        self.assertIn('/skills/espresso', physics)
        self.assertIn('/roles/waiter', self.url_open('/knowledge/isco-08/5131').text)
        self.assertIn('/knowledge/isced-f-2013/053', self.url_open('/knowledge/isced-f-2013/05').text)
        self.assertEqual(self.url_open('/knowledge/nope/05').status_code, 404)
        self.assertIn('/roles/barista', self.url_open('/roles?q=باریسته').text, "works without JavaScript")

    def test_suggest_endpoint(self):
        results = self.url_open('/standard/suggest?kind=role&q=گارسون').json()['results']
        self.assertEqual((results[0]['label'], results[0]['url']), ("پذیرایی از مهمان", '/roles/waiter'))
        hidden = [r['url'] for r in self.url_open('/standard/suggest?kind=role&q=بارتندر').json()['results']]
        self.assertNotIn('/roles/bartender', hidden, "withheld here; a non-alcoholic mixologist may still come up")
        skills = self.url_open('/standard/suggest?kind=skill&q=اسپرسو').json()['results']
        self.assertIn('/skills/espresso', [r['url'] for r in skills])
        knowledge = self.url_open('/standard/suggest?kind=knowledge&q=physics').json()['results']
        self.assertIn('/knowledge/isced-f-2013/0533', [r['url'] for r in knowledge])
        self.assertEqual(self.url_open('/standard/suggest?kind=other&q=x').json()['results'], [])

    def test_the_tile_screens_offer_typing(self):
        portal = self.env.ref('base.group_portal')
        user = self.env['res.users'].create({'name': "سارا احمدی", 'login': 'std-pick', 'password': 'std-pick-pass-1',
                                             'group_ids': [(6, 0, [portal.id])]})
        user.partner_id._ikiku_grant_role('ki')
        user.partner_id._ikiku_grant_role('ku', business_name="کافه")
        self.authenticate('std-pick', 'std-pick-pass-1')
        for url in ('/join/skills', '/business/need/who'):
            page = self.url_open(url).text
            self.assertIn('data-ikiku-pick', page, url)
            self.assertIn('/standard/suggest?kind=role', page, url)
            self.assertIn("کارهای دیگه", page, url)
            self.assertNotIn("بارتندر", page, url)
            self.assertIn('ikiku__subgroup', page, url)
            self.assertIn("غذای ایرانی", page, url)
