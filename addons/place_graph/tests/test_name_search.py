# Part of place_graph. Licensed under AGPL-3.0.
"""A place's many2one box in the back office: what the site's place box would answer."""
from odoo.models import BaseModel
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPlaceNameSearch(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Place = cls.env['place.node']
        iran = Place.create({'name': "ایران", 'code': 'nstest-ir', 'kind': 'country', 'in_path': False})
        cls.tehran = Place.create({'name': "تهران", 'code': 'nstest-ir-tehran', 'kind': 'city', 'parent_id': iran.id})
        cls.palestine = Place.create({'name': "فلسطین", 'code': 'nstest-ir-tehran-palestine', 'kind': 'neighbourhood',
                                      'parent_id': cls.tehran.id, 'alias_ids': [(0, 0, {'name': "کاخ", 'kind': 'old'})]})
        cls.mashhad = Place.create({'name': "مشهد", 'code': 'nstest-ir-mashhad', 'kind': 'city', 'parent_id': iran.id})
        cls.palestine_mashhad = Place.create({'name': "فلسطین", 'code': 'nstest-ir-mashhad-palestine',
                                              'kind': 'neighbourhood', 'parent_id': cls.mashhad.id})
        cls.karaj = Place.create({'name': "کرج", 'code': 'nstest-ir-karaj', 'kind': 'city', 'parent_id': iran.id})
        cls.only = [('code', 'like', 'nstest-%')]

    def found(self, query, domain=None):
        return [record_id for record_id, _name in
                self.env['place.node'].name_search(query, (domain or []) + self.only, 'ilike', 8)]

    def test_an_old_name_finds_the_place(self):
        self.assertEqual(self.found("کاخ"), [self.palestine.id])
        self.assertEqual(BaseModel.name_search(self.env['place.node'], "کاخ", self.only, 'ilike', 8), [],
                         "Odoo's own search knew no old name")

    def test_letters_as_a_keyboard_types_them(self):
        self.assertEqual(self.found("كرج"), [self.karaj.id], "an Arabic kaf")
        self.assertEqual(set(self.found("فلسطين")), {self.palestine.id, self.palestine_mashhad.id}, "an Arabic yeh")

    def test_the_sites_order_and_the_boxs_domain(self):
        ranked = self.env['place.node'].suggest_places("فلسطین", domain=self.only, limit=8)
        self.assertEqual(self.found("فلسطین"), [result['record'].id for result in ranked])
        self.assertEqual(self.found("فلسطین", [('parent_id', '=', self.mashhad.id)]), [self.palestine_mashhad.id])

    def test_the_answer_reads_as_the_path(self):
        name = dict(self.env['place.node'].name_search("کاخ", self.only, 'ilike', 8))[self.palestine.id]
        self.assertEqual(name, self.palestine.display_name)
        self.assertEqual(name, "فلسطین · تهران")
