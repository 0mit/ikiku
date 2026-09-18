# Part of iKiKu. Licensed under AGPL-3.0.
"""Where a café is, where a person is, and what each of those lets the other see.

Three things are being asked here, and each of them is a decision somebody made:
  - a person says a city and nothing finer, and a café may say its street (operator, 2026-09-18);
  - a card shows the neighbourhood of a need whose place is a street, because
    `place_public_id` is what a page is given and the street is not in it;
  - how near two places are enters the ranking as one readable step, and the explanation
    names the step in words.
"""
from odoo.tests import HttpCase, TransactionCase, tagged


def place(env, name, kind='city'):
    found = env['place.node'].sudo().search([('kind', '=', kind), ('name', '=', name)], limit=1)
    assert found, "place_ir has no %s called %s" % (kind, name)
    return found


@tagged('post_install', '-at_install')
class TestPlacesOnRecords(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.tehran = place(env, "تهران")
        cls.district6 = place(env, "منطقه ۶", 'district')
        cls.university = place(env, "دانشگاه تهران", 'neighbourhood')
        cls.palestine = env['place.node'].sudo().search(
            [('kind', '=', 'street'), ('name', '=', "فلسطین"),
             ('parent_id', '=', cls.university.id)], limit=1)
        assert cls.palestine, "place_ir has no street فلسطین in دانشگاه تهران"
        owner = env['res.partner'].create({'name': "کافه‌دار"})
        cls.business = env['ikiku.business'].create({'name': "کافهٔ آزمایشی", 'partner_id': owner.id,
                                                    'place_id': cls.palestine.id})
        position = env['ikiku.position'].create({
            'name': "باریستا", 'business_id': cls.business.id,
            'spec_node_id': env.ref('ikiku_base.spec_barista').id})
        cls.need = env['ikiku.demand'].create({
            'business_id': cls.business.id, 'position_id': position.id,
            'place_id': cls.palestine.id, 'seats': 1, 'state': 'open'})

    def test_a_cafe_on_a_street_is_public_as_its_neighbourhood(self):
        self.assertEqual(self.need.place_id, self.palestine)
        self.assertEqual(self.need.place_public_id, self.university)
        self.assertEqual(self.need.city, "تهران")
        self.assertEqual(self.need.province_id.name, "استان تهران")
        # and the card built for the public says the neighbourhood, never the street
        cards = self.env['ikiku.demand'].ikiku_public_open()
        mine = [card for card in cards if card.get('place', '').startswith("دانشگاه تهران")]
        self.assertTrue(mine, "the card should carry the neighbourhood: %s" % cards)
        self.assertFalse(any("فلسطین" in (card.get('place') or '') for card in cards))

    def test_a_person_is_placed_no_finer_than_their_city(self):
        partner = self.env['res.partner'].create({'name': "کارجو", 'place_id': self.palestine.id})
        # A person's record may hold a fine place, and what it shows is the city.
        self.assertEqual(partner.place_public_id, self.tehran)
        self.assertEqual(partner.ikiku_city, "تهران")

    def test_a_post_code_names_an_area_and_only_its_prefix_is_kept(self):
        Postcode = self.env['place.postcode']
        Postcode.create({'prefix': '14167', 'place_id': self.university.id, 'source': 'staff'})
        self.assertEqual(Postcode.place_for_code("1416753955"), self.university)
        self.assertEqual(Postcode.place_for_code("۱۴۱۶۷۵۳۹۵۵"), self.university)
        self.assertFalse(Postcode.search([('prefix', 'like', '1416753%')]),
                         "nothing longer than the prefix is stored")


@tagged('post_install', '-at_install')
class TestNearness(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.university = place(env, "دانشگاه تهران", 'neighbourhood')
        cls.karaj = place(env, "کرج")
        cls.tehran = place(env, "تهران")
        cls.isfahan = place(env, "اصفهان")
        owner = env['res.partner'].create({'name': "کافه‌دار"})
        business = env['ikiku.business'].create({'name': "کافه", 'partner_id': owner.id,
                                                 'place_id': cls.university.id})
        position = env['ikiku.position'].create({
            'name': "باریستا", 'business_id': business.id,
            'spec_node_id': env.ref('ikiku_base.spec_barista').id})
        cls.need = env['ikiku.demand'].create({
            'business_id': business.id, 'position_id': position.id,
            'place_id': cls.university.id, 'seats': 1, 'state': 'open'})
        worker = env['res.partner'].create({'name': "کارجو"})
        cls.resource = env['ikiku.resource'].create({'partner_id': worker.id, 'state': 'active'})

    def availability(self, node, relocate=False):
        """The one availability this person has, moved. Two at once would overlap in time,
        which the model refuses -- nobody is free in two places on the same day."""
        current = self.env['ikiku.availability'].search([('resource_id', '=', self.resource.id)], limit=1)
        values = {'place_id': node.id, 'can_relocate': relocate}
        if current:
            current.write(values)
            return current
        return self.env['ikiku.availability'].create(dict(values, resource_id=self.resource.id))

    def nearness(self, node, relocate=False):
        return self.env['ikiku.proposal']._nearness(self.need, self.availability(node, relocate))

    def test_nearness_is_read_off_the_tree_step_by_step(self):
        self.assertEqual(self.nearness(self.university), 'same_place')
        # Somewhere else in the same city is further than the same neighbourhood.
        self.assertEqual(self.nearness(self.tehran), 'same_city')
        # Another city in another province, unless they said they can move.
        self.assertEqual(self.nearness(self.isfahan), 'far')
        self.assertEqual(self.nearness(self.isfahan, relocate=True), 'can_relocate')

    def test_a_neighbouring_neighbourhood_beats_the_far_side_of_town(self):
        neighbour = self.university.neighbour_ids[:1]
        if not neighbour:
            self.skipTest("the map gives دانشگاه تهران no neighbour")
        self.assertEqual(self.nearness(neighbour), 'neighbouring_area')
        near = self.env['ikiku.proposal']._score(
            self.need, self.resource, self.availability(neighbour))
        far = self.env['ikiku.proposal']._score(
            self.need, self.resource, self.availability(self.isfahan))
        self.assertGreater(near['score_proximity'], far['score_proximity'])
        self.assertIn("محلهٔ همسایه", near['explanation'])
        self.assertIn("جای دیگر", far['explanation'])


@tagged('post_install', '-at_install')
class TestPostCodeLearning(HttpCase):
    """A café that gives a code and confirms a place teaches the table what that prefix means."""

    def test_a_confirmed_place_with_a_code_is_learned_and_the_code_is_not_kept(self):
        Postcode = self.env['place.postcode']
        university = place(self.env, "دانشگاه تهران", 'neighbourhood')
        self.assertFalse(Postcode.search([('prefix', '=', '14167')]))
        # The controller's own step, which is what the need form calls on every save.
        Postcode.learn("1416753955", university)
        Postcode.learn("۱۴۱۶۷-۵۳۹۵۵", university)
        learned = Postcode.search([('prefix', '=', '14167')])
        self.assertEqual((learned.place_id, learned.source, learned.hits), (university, 'learned', 2))
        self.assertEqual(len(learned.prefix), 5)


@tagged('post_install', '-at_install')
class TestPlaceSuggestPage(HttpCase):

    def test_the_suggest_endpoint_answers_anybody_and_says_where_each_place_is(self):
        answer = self.url_open('/places/suggest?q=%s' % "کاخ").json()
        paths = [result['detail'] for result in answer['results']]
        self.assertTrue(any(path.startswith("فلسطین") for path in paths),
                        "«کاخ» should reach فلسطین: %s" % paths)
        # The quick answer is the one a page shows first: the same ranking, from the tightest
        # search, and everything in it is in the full answer too.
        quick = self.url_open('/places/suggest?q=%s&quick=1' % "تهران").json()
        full = self.url_open('/places/suggest?q=%s' % "تهران").json()
        self.assertTrue(quick['results'])
        self.assertLessEqual({result['id'] for result in quick['results']},
                             {result['id'] for result in full['results']})

    def test_the_endpoint_answers_places_and_nothing_else(self):
        answer = self.url_open('/places/suggest?q=%s' % "تهران").json()
        self.assertTrue(answer['results'])
        for result in answer['results']:
            # The place, and why it was found (the published ranking, the responder's shape):
            # nothing about anybody who is there.
            self.assertEqual(set(result), {'id', 'code', 'label', 'detail', 'kind', 'score', 'field', 'match'})


@tagged('post_install', '-at_install')
class TestPlaceBox(HttpCase):
    """The «کجا؟» box: which door it asks, what the server accepts back, and what it learns
    from a search that found nothing."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        portal = cls.env.ref('base.group_portal')
        cls.env['res.users'].create({'name': "جا آزما", 'login': 'box-worker', 'password': 'box-worker-pass-1',
                                     'group_ids': [(6, 0, [portal.id])]})
        cls.karaj = place(cls.env, "کرج")

    def post(self, url, data):
        import re
        token = re.search(r'name="csrf_token" value="([^"]+)"', self.url_open(url).text).group(1)
        return self.url_open(url, data=dict(data, csrf_token=token), allow_redirects=False)

    def test_the_box_asks_the_responder_and_falls_back_to_odoo(self):
        self.authenticate('box-worker', 'box-worker-pass-1')
        self.url_open('/join')
        page = self.url_open('/join/where').text
        self.assertIn('data-suggest-url="/places/suggest"', page, "no responder configured: Odoo answers")
        self.assertNotIn('data-suggest-fallback', page)
        self.assertIn('data-suggest-busy', page, "the کو sign of waiting is in the box")
        self.env['ir.config_parameter'].sudo().set_param('place_graph.responder_url', '/places/q')
        page = self.url_open('/join/where').text
        self.assertIn('data-suggest-url="/places/q"', page)
        self.assertIn('data-suggest-fallback="/places/suggest"', page)

    def test_odoo_answers_in_the_responders_shape(self):
        results = self.url_open('/places/suggest?q=%s&kinds=city' % "کرج").json()['results']
        self.assertTrue(results)
        self.assertEqual(results[0]['id'], self.karaj.id)
        self.assertTrue({'code', 'label', 'detail', 'kind', 'score', 'field', 'match'} <= set(results[0]))

    def test_an_archived_place_sent_back_is_not_accepted(self):
        self.authenticate('box-worker', 'box-worker-pass-1')
        self.url_open('/join')
        gone = self.env['place.node'].sudo().create({'name': "ویرانه", 'code': 'test-box-gone', 'kind': 'city',
                                                     'active': False})
        response = self.post('/join/where', {'place_id': str(gone.id), 'place_q': ''})
        self.assertEqual(response.status_code, 200, "the id is ignored and the empty text is asked again")
        self.assertFalse(self.env['res.users'].search([('login', '=', 'box-worker')]).partner_id.place_id)

    def test_a_search_that_found_nothing_is_offered_to_an_editor(self):
        self.authenticate('box-worker', 'box-worker-pass-1')
        self.url_open('/join')
        Suggestion = self.env['place.suggestion'].sudo()
        self.post('/join/where', {'place_id': str(self.karaj.id), 'place_q': "کرج",
                                  'place_missed': "مهرشهر قدیم"})
        offered = Suggestion.search([('place_id', '=', self.karaj.id), ('name', '=', "مهرشهر قدیم")])
        self.assertEqual((offered.action, offered.origin, offered.state), ('alias', 'portal', 'proposed'))
        self.assertFalse(self.karaj.alias_ids.filtered(lambda a: a.name == "مهرشهر قدیم"),
                         "offered, not written: an editor decides")
        # A post code is never kept, not even as a suggestion.
        self.post('/join/where', {'place_id': str(self.karaj.id), 'place_q': "کرج",
                                  'place_missed': "۳۱۵۸۷۶۵۴۳۲"})
        self.assertFalse(Suggestion.search([('name', 'like', '3158')]))
        self.assertFalse(Suggestion.search([('name', 'like', '۳۱۵۸')]))


@tagged('post_install', '-at_install')
class TestPersonNeighbourhood(HttpCase):
    """A person's neighbourhood is public only if THEY give it (بند ۷; the operator, 2026-09-18)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        portal = cls.env.ref('base.group_portal')
        cls.user = cls.env['res.users'].create({'name': "محله آزما", 'login': 'area-worker',
                                                'password': 'area-worker-pass-1',
                                                'group_ids': [(6, 0, [portal.id])]})
        cls.tehran = place(cls.env, "تهران")
        cls.university = place(cls.env, "دانشگاه تهران", 'neighbourhood')
        cls.mashhad = place(cls.env, "مشهد")
        cls.elsewhere = cls.env['place.node'].sudo().search(
            [('kind', '=', 'neighbourhood'), ('parent_path', '=like', cls.mashhad.parent_path + '%')], limit=1)

    def post(self, data):
        import re
        token = re.search(r'name="csrf_token" value="([^"]+)"', self.url_open('/join/where').text).group(1)
        return self.url_open('/join/where', data=dict(data, csrf_token=token), allow_redirects=False)

    def partner(self):
        return self.user.partner_id.sudo()

    def test_a_neighbourhood_given_is_shown_and_one_not_given_is_not(self):
        self.authenticate('area-worker', 'area-worker-pass-1')
        self.url_open('/join')
        self.assertIn('name="place_area_q"', self.url_open('/join/where').text, "the choice is offered")
        # Given: kept and shown.
        self.assertEqual(self.post({'place_id': str(self.tehran.id), 'place_q': "تهران",
                                    'place_area_id': str(self.university.id)}).status_code, 303)
        partner = self.partner()
        self.assertEqual((partner.place_id, partner.ikiku_show_neighbourhood), (self.university, True))
        self.assertEqual(partner.place_public_id, self.university)
        self.assertEqual(partner.ikiku_city, "تهران")
        # Left empty: only the city is kept, and the neighbourhood given before is let go of.
        self.assertEqual(self.post({'place_id': str(self.tehran.id), 'place_q': "تهران"}).status_code, 303)
        partner.invalidate_recordset()
        self.assertEqual((partner.place_id, partner.ikiku_show_neighbourhood), (self.tehran, False))
        self.assertEqual(partner.place_public_id, self.tehran)

    def test_a_neighbourhood_outside_the_city_or_an_address_is_refused(self):
        self.authenticate('area-worker', 'area-worker-pass-1')
        self.url_open('/join')
        if self.elsewhere:
            refused = self.post({'place_id': str(self.tehran.id), 'place_q': "تهران",
                                 'place_area_id': str(self.elsewhere.id), 'place_area_q': "نامعلوم‌آباد"})
            self.assertEqual(refused.status_code, 200)
            self.assertFalse(self.partner().place_id, "nothing is saved while the answer is wrong")
        address = self.post({'place_id': str(self.tehran.id), 'place_q': "تهران",
                             'place_area_q': "خیابان آزادی پلاک ۱۲"})
        self.assertEqual(address.status_code, 200)
        self.assertIn("پلاک و کد پستی لازم نیست", address.text)
        self.assertFalse(self.partner().ikiku_show_neighbourhood)


@tagged('post_install', '-at_install')
class TestPersonPublicFace(TransactionCase):

    def test_the_public_face_follows_the_persons_choice(self):
        university = place(self.env, "دانشگاه تهران", 'neighbourhood')
        partner = self.env['res.partner'].create({'name': "آزما", 'place_id': university.id})
        self.assertEqual(partner.place_public_id, place(self.env, "تهران"), "by default: the city")
        partner.ikiku_show_neighbourhood = True
        self.assertEqual(partner.place_public_id, university, "chosen: the neighbourhood")
        partner.ikiku_show_neighbourhood = False
        self.assertEqual(partner.place_public_id.kind, 'city')
