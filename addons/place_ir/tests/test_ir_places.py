# Part of place_ir. Licensed under AGPL-3.0.
"""The data, asked the questions a person would ask it."""
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestIranPlaces(TransactionCase):

    def places(self, query, **kw):
        return self.env['place.node'].suggest_places(query, **kw)

    def test_the_country_is_there_with_its_provinces(self):
        Place = self.env['place.node']
        self.assertEqual(Place.search_count([('kind', '=', 'province')]), 31)
        tehran = Place.search([('kind', '=', 'city'), ('name', '=', "تهران")], limit=1)
        self.assertTrue(tehran)
        self.assertEqual(tehran.path, "تهران · استان تهران")
        # A county is loaded and stays out of what a person reads.
        self.assertTrue(Place.search_count([('kind', '=', 'county')]) > 1000)
        self.assertFalse(Place.search([('kind', '=', 'county')], limit=1).in_path)

    def test_a_former_name_finds_the_street_it_belongs_to(self):
        # The operator's example: «کاخ» is what people still call خیابان فلسطین, in Tehran.
        found = self.places("کاخ", within=self.city("تهران"))
        paths = [result['record'].path for result in found]
        self.assertTrue(any(path.startswith("فلسطین") for path in paths),
                        "«کاخ» should reach فلسطین, got %s" % paths[:5])

    def test_a_neighbourhood_reads_as_its_district_and_city(self):
        place = self.env['place.node'].search(
            [('kind', '=', 'neighbourhood'), ('name', '=', "دانشگاه تهران")], limit=1)
        self.assertEqual(place.path, "دانشگاه تهران · منطقه ۶ · تهران")

    def test_the_city_you_are_in_decides_between_places_of_the_same_name(self):
        in_tehran = self.places("فلسطین", within=self.city("تهران"))[0]['record']
        in_mashhad = self.places("فلسطین", within=self.city("مشهد"))[0]['record']
        self.assertIn("تهران", in_tehran.path)
        self.assertIn("مشهد", in_mashhad.path)

    def test_places_have_neighbours(self):
        linked = self.env['place.link'].search_count([])
        self.assertGreater(linked, 10000)

    def city(self, name):
        return self.env['place.node'].search([('kind', '=', 'city'), ('name', '=', name)], limit=1)
