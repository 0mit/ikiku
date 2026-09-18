# Part of place_graph. Licensed under AGPL-3.0.
"""What a person types, and the place they meant."""
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPlace(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Place = cls.env['place.node']
        cls.iran = Place.create({'name': "ایران", 'code': 'test-ir', 'kind': 'country',
                                 'in_path': False})
        cls.tehran_province = Place.create({'name': "تهران", 'code': 'test-ir-te', 'kind': 'province',
                                            'parent_id': cls.iran.id})
        # A county is real and nobody picks one: it holds its cities and stays out of the path.
        cls.county = Place.create({'name': "شهرستان تهران", 'code': 'test-ir-te-c-tehran',
                                   'kind': 'county', 'parent_id': cls.tehran_province.id,
                                   'in_path': False})
        cls.tehran = Place.create({'name': "تهران", 'code': 'test-ir-te-tehran', 'kind': 'city',
                                   'parent_id': cls.county.id})
        cls.district6 = Place.create({'name': "منطقهٔ ۶", 'code': 'test-ir-te-tehran-6',
                                      'kind': 'district', 'parent_id': cls.tehran.id})
        cls.palestine = Place.create({
            'name': "فلسطین", 'code': 'test-ir-te-tehran-6-palestine', 'kind': 'neighbourhood',
            'parent_id': cls.district6.id,
            'alias_ids': [(0, 0, {'name': "کاخ", 'kind': 'old'})]})
        cls.valiasr = Place.create({'name': "ولیعصر", 'code': 'test-ir-te-tehran-6-valiasr',
                                    'kind': 'neighbourhood', 'parent_id': cls.district6.id})
        # The same name in another city, to make sure context decides between them.
        cls.mashhad = Place.create({'name': "مشهد", 'code': 'test-ir-rk-mashhad', 'kind': 'city',
                                    'parent_id': cls.iran.id})
        cls.palestine_mashhad = Place.create({'name': "فلسطین", 'code': 'test-ir-rk-mashhad-palestine',
                                              'kind': 'neighbourhood', 'parent_id': cls.mashhad.id})

    # The fixture's own codes all start with this, so these tests answer from the fixture
    # even where a whole country's places are loaded beside it.
    ONLY_FIXTURE = [('code', 'like', 'test-%')]

    def found(self, query, **kw):
        kw.setdefault('domain', self.ONLY_FIXTURE)
        return [result['record'] for result in self.env['place.node'].suggest_places(query, **kw)]

    # --------------------------------------------------------------------- tree
    def test_a_layer_nobody_picks_is_kept_and_left_out_of_the_path(self):
        self.assertEqual(self.tehran.path, "تهران")        # said once, not «تهران · تهران»
        self.assertEqual(self.palestine.path, "فلسطین · منطقهٔ ۶ · تهران")
        self.assertIn(self.county, self.palestine.ancestor_places())
        # It is still searchable: a county name leads to the city under it.
        self.assertIn(self.tehran, self.found("شهرستان تهران"))

    def test_a_place_cannot_be_inside_itself(self):
        # Odoo's own parent_store check fires first; _check_acyclic stands behind it.
        with self.assertRaises(UserError):
            self.district6.parent_id = self.palestine

    # -------------------------------------------------------------------- names
    def test_an_old_name_finds_the_place_and_never_replaces_its_name(self):
        found = self.found("کاخ")
        self.assertEqual(found[:1], [self.palestine])
        self.assertEqual(self.palestine.display_name, "فلسطین · منطقهٔ ۶ · تهران")
        self.assertNotIn("کاخ", self.palestine.display_name)

    def test_naming_a_neighbour_finds_the_place(self):
        self.env['place.link'].create({'place_id': self.palestine.id, 'other_id': self.valiasr.id})
        self.assertIn(self.palestine, self.found("ولیعصر"))
        # and the place itself still wins for its own name
        self.assertEqual(self.found("ولیعصر")[0], self.valiasr)

    def test_the_place_you_are_in_wins_over_the_same_name_elsewhere(self):
        everywhere = self.found("فلسطین")
        self.assertEqual(set(everywhere) & {self.palestine, self.palestine_mashhad},
                         {self.palestine, self.palestine_mashhad})
        in_tehran = self.env['place.node'].suggest_places("فلسطین", within=self.tehran,
                                                          domain=self.ONLY_FIXTURE)
        self.assertEqual(in_tehran[0]['record'], self.palestine)
        self.assertGreater(in_tehran[0].get('boost', 1.0), 1.0)
        in_mashhad = self.env['place.node'].suggest_places("فلسطین", within=self.mashhad,
                                                           domain=self.ONLY_FIXTURE)
        self.assertEqual(in_mashhad[0]['record'], self.palestine_mashhad)

    def test_the_quick_answer_is_part_of_the_full_one(self):
        # The quick answer is the tightest search: what is CALLED this. It can miss what a
        # wider one finds -- here a mistyped word -- which is why it is only what a page
        # shows while the full answer is still coming.
        self.assertIn(self.palestine, self.found("کاخ", widen=False))
        self.assertFalse(self.found("کاخخ", widen=False))
        self.assertIn(self.palestine, self.found("کاخخ"), "a mistyped word still reaches it")

    def test_a_kind_narrows_the_answer(self):
        self.assertEqual(self.found("تهران", kinds=('city',)), [self.tehran])

    # -------------------------------------------------------------------- graph
    def test_a_neighbour_is_a_neighbour_from_both_sides(self):
        Link = self.env['place.link']
        link = Link.create({'place_id': self.palestine.id, 'other_id': self.valiasr.id,
                            'relation': 'adjacent'})
        self.assertEqual(self.valiasr.neighbour_ids, self.palestine)
        self.assertEqual(self.palestine.neighbour_ids, self.valiasr)
        link.unlink()
        self.assertFalse(self.valiasr.neighbour_ids)
        self.assertFalse(self.palestine.neighbour_ids)

    def test_a_place_is_not_its_own_neighbour(self):
        with self.assertRaises(ValidationError):
            self.env['place.link'].create({'place_id': self.palestine.id,
                                           'other_id': self.palestine.id})

    # ---------------------------------------------------------------- postcodes
    def test_only_the_prefix_of_a_post_code_is_ever_read(self):
        Postcode = self.env['place.postcode']
        self.assertEqual(Postcode.prefix_of("1416753955"), '14167')
        self.assertEqual(Postcode.prefix_of("۱۴۱۶۷-۵۳۹۵۵"), '14167')
        self.assertFalse(Postcode.prefix_of("1416"))

    def test_what_people_confirm_beats_an_imported_table_once_enough_of_them_agree(self):
        Postcode = self.env['place.postcode']
        Postcode.create({'prefix': '14167', 'place_id': self.valiasr.id, 'source': 'import'})
        self.assertEqual(Postcode.place_for_code("1416753955"), self.valiasr)
        for _ in range(3):
            Postcode.learn("1416753955", self.palestine)
        self.assertEqual(Postcode.place_for_code("1416753955"), self.palestine)
        self.assertEqual(Postcode.search([('prefix', '=', '14167'),
                                          ('place_id', '=', self.palestine.id)]).hits, 3)
        # Staff outrank both, and no row anywhere holds more than the prefix.
        Postcode.create({'prefix': '14167', 'place_id': self.district6.id, 'source': 'staff'})
        self.assertEqual(Postcode.place_for_code("1416753955"), self.district6)
        self.assertEqual(set(Postcode.search([]).mapped(lambda r: len(r.prefix))), {5})

    def test_a_post_code_that_is_not_known_answers_nothing(self):
        self.assertFalse(self.env['place.postcode'].place_for_code("9999999999"))

    def test_a_finer_match_answers_as_the_city_on_a_form_that_asks_for_one(self):
        # The operator, 2026-09-18: «کرشته» and «کاخ» found nothing on the worker's city form,
        # because the places they name are a neighbourhood and a street.
        found = self.env['place.node'].suggest_places("کاخ", kinds=('city', 'village', 'province'),
                                                       domain=self.ONLY_FIXTURE)
        self.assertEqual(found[0]['record'], self.tehran)
        self.assertEqual(found[0]['via'], self.palestine, "and it says which place it came through")

    def test_a_county_is_not_lifted_to_its_province(self):
        # Coarser than what the form offers is simply not an answer: nothing answers THROUGH
        # the county (the province still answers on its own name, «تهران»).
        found = self.env['place.node'].suggest_places(
            "شهرستان تهران", kinds=('city', 'village', 'province'), domain=self.ONLY_FIXTURE)
        self.assertNotIn(self.county, [r['record'] for r in found])
        self.assertFalse([r for r in found if r.get('via') == self.county])

    def test_equal_scores_fall_to_the_order_of_the_city(self):
        self.tehran.sequence, self.mashhad.sequence = 41, 42
        found = [r['record'] for r in self.env['place.node'].suggest_places("فلسطین", domain=self.ONLY_FIXTURE)]
        self.assertEqual(found[:2], [self.palestine, self.palestine_mashhad])
        self.tehran.sequence, self.mashhad.sequence = 43, 42
        found = [r['record'] for r in self.env['place.node'].suggest_places("فلسطین", domain=self.ONLY_FIXTURE)]
        self.assertEqual(found[:2], [self.palestine_mashhad, self.palestine])

    def test_a_neighbourhood_comes_before_a_street_of_the_same_name_whatever_the_city(self):
        # The operator, 2026-09-18: «بعثت» meant the neighbourhoods; streets called that in a
        # bigger city had jumped ahead of them when the city's order was put first.
        self.tehran.sequence, self.mashhad.sequence = 41, 42
        street = self.env['place.node'].create({'name': "فلسطین", 'code': 'test-ir-te-tehran-street',
                                                'kind': 'street', 'parent_id': self.tehran.id, 'sequence': 190})
        self.palestine.sequence = self.palestine_mashhad.sequence = 150
        found = [r['record'] for r in self.env['place.node'].suggest_places("فلسطین", domain=self.ONLY_FIXTURE)]
        self.assertLess(found.index(self.palestine_mashhad), found.index(street))
