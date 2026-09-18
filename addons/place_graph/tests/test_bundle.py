# Part of place_graph. Licensed under AGPL-3.0.
"""A bundle taken in, taken in again, and changed -- and what people decided, left alone."""
import json
import os
import shutil
import tempfile

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged

from odoo.addons.place_graph.models.place import NOTIFY_CHANNEL, SPEC_PARAM
from odoo.addons.place_graph.tools import bundle, tree

PLACES = [
    # code, name, name_en, kind, parent, in_path
    ('zz-land', "زدستان", 'Zedland', 'country', '', 'False'),
    ('zz-north', "استان شمال", '', 'province', 'zz-land', 'True'),
    ('zz-north-county', "شهرستان مرکز", '', 'county', 'zz-north', 'False'),
    ('zz-town', "شهرک", 'Town', 'city', 'zz-north-county', 'True'),
    ('zz-town-1', "منطقه ۱", '', 'district', 'zz-town', 'True'),
    ('zz-bazaar', "بازارچه", '', 'neighbourhood', 'zz-town-1', 'True'),
    ('zz-garden', "باغستان", '', 'neighbourhood', 'zz-town-1', 'True'),
    ('zz-old', "کهنه‌ده", '', 'village', 'zz-north-county', 'True'),
]
ALIASES = [('zz-town', "شهر قدیم", 'old'), ('zz-bazaar', "میدان مس", 'square')]
LINKS = [('zz-bazaar', 'zz-garden', 'adjacent')]
POSTCODES = [('99999', 'zz-bazaar', 'import', '0')]


@tagged('post_install', '-at_install')
class TestBundle(TransactionCase):

    def setUp(self):
        super().setUp()
        self.dir = tempfile.mkdtemp(prefix='place-bundle-')
        self.addCleanup(shutil.rmtree, self.dir)
        self.Place = self.env['place.node']

    def write(self, places=PLACES, aliases=ALIASES, links=LINKS, postcodes=POSTCODES):
        header = bundle.FILES
        bundle.write_csv(os.path.join(self.dir, 'places.csv'), header['places.csv'], [
            dict(code=c, name=n, name_en=e, kind=k, parent=p, in_path=i, latitude='', longitude='',
                 source='test') for c, n, e, k, p, i in places])
        bundle.write_csv(os.path.join(self.dir, 'aliases.csv'), header['aliases.csv'], [
            dict(place=p, name=n, kind=k, source='test') for p, n, k in aliases])
        bundle.write_csv(os.path.join(self.dir, 'links.csv'), header['links.csv'], [
            dict(place=a, other=b, relation=r, source='test') for a, b, r in links])
        bundle.write_csv(os.path.join(self.dir, 'postcodes.csv'), header['postcodes.csv'], [
            dict(prefix=x, place=p, source=s, hits=h) for x, p, s, h in postcodes])
        bundle.seal(self.dir, country='zz')

    def load(self, **kw):
        return self.Place.sudo().load_bundle(self.dir, **kw)

    def at(self, code):
        return self.Place.with_context(active_test=False).search([('code', '=', code)])

    # ----------------------------------------------------------------- loading
    def test_a_loaded_place_reads_as_an_edited_one(self):
        self.write()
        summary = self.load()
        self.assertEqual(summary['places_added'], len(PLACES))
        bazaar = self.at('zz-bazaar')
        self.assertEqual(bazaar.origin, 'bundle')
        self.assertEqual(bazaar.path, "بازارچه · منطقه ۱ · شهرک")
        self.assertEqual(bazaar.parent_path, ''.join('%d/' % p.id for p in (
            self.at('zz-land'), self.at('zz-north'), self.at('zz-north-county'), self.at('zz-town'),
            self.at('zz-town-1'), bazaar)))
        # What the loader wrote is what the model computes for the same row.
        stored = (bazaar.path, bazaar.suggest_index)
        bazaar.invalidate_recordset()
        bazaar._compute_path()
        bazaar._compute_suggest_index()
        self.assertEqual((bazaar.path, bazaar.suggest_index), stored)
        # and it is found by the square in it and by the neighbour beside it
        found = [r['record'] for r in self.Place.suggest_places("میدان مس", domain=[('code', 'like', 'zz-%')])]
        self.assertEqual(found[:1], [bazaar])
        self.assertIn(bazaar, self.at('zz-garden').neighbour_ids)
        self.assertEqual(self.env['place.postcode'].place_for_code("9999912345"), bazaar)

    def test_the_same_bundle_again_costs_a_hash(self):
        self.write()
        self.load()
        self.assertEqual(self.load(), {'state': 'unchanged'})

    def test_a_changed_bundle_loads_its_difference(self):
        self.write()
        self.load()
        garden = self.at('zz-garden')
        places = [row for row in PLACES if row[0] != 'zz-old']            # a village gone
        places = [(c, "بازار بزرگ" if c == 'zz-bazaar' else n, e, k, p, i) for c, n, e, k, p, i in places]
        places.append(('zz-new', "نوساز", '', 'neighbourhood', 'zz-town-1', 'True'))
        self.write(places=places, aliases=[ALIASES[0]], links=[], postcodes=[])
        summary = self.load()
        self.assertEqual((summary['places_added'], summary['places_changed'], summary['places_retired']),
                         (1, 1, 1))
        self.assertEqual(self.at('zz-bazaar').name, "بازار بزرگ")
        self.assertEqual(self.at('zz-bazaar').path, "بازار بزرگ · منطقه ۱ · شهرک")
        self.assertFalse(self.at('zz-old').active, "a place the bundle dropped is archived, not deleted")
        self.assertFalse(self.at('zz-bazaar').alias_ids, "an alias the bundle dropped is removed")
        self.assertFalse(garden.neighbour_ids, "a pair the bundle dropped is removed both ways")
        self.assertFalse(self.env['place.postcode'].search([('prefix', '=', '99999')]))

    # ----------------------------------------------------------------- overlay
    def test_what_a_person_decided_outlives_every_load(self):
        self.write()
        self.load()
        bazaar = self.at('zz-bazaar')
        bazaar.write({'name': "بازار مسگرها"})                  # staff renamed an imported place
        self.assertEqual(bazaar.kept_fields, 'name')
        own = self.env['place.alias'].create({'place_id': bazaar.id, 'name': "راسته", 'kind': 'colloquial'})
        self.assertEqual(own.origin, 'overlay')
        square = bazaar.alias_ids.filtered(lambda a: a.name == "میدان مس")
        square.unlink()                                         # staff removed an imported alias
        self.assertFalse(square.active, "an imported alias a person removes is archived")
        local = self.Place.create({'name': "کوچه باغ", 'code': 'zz-local-1', 'kind': 'street',
                                   'parent_id': bazaar.id})
        self.assertEqual(local.origin, 'overlay')

        self.write(places=[row for row in PLACES], aliases=ALIASES)   # same content, new seal
        self.load(force=True)
        self.assertEqual(bazaar.name, "بازار مسگرها", "the bundle does not undo a person's rename")
        self.assertTrue(own.exists() and own.active)
        self.assertFalse(square.active, "the bundle does not bring back what a person removed")
        self.assertTrue(local.exists() and local.active, "the bundle never retires the overlay")
        self.assertEqual(local.path, "کوچه باغ · بازار مسگرها · شهرک")

    def test_only_an_administrator_loads_a_bundle(self):
        self.write()
        user = self.env['res.users'].create({'name': "Editor", 'login': 'place-editor-test',
                                             'group_ids': [(4, self.env.ref('base.group_user').id)]})
        with self.assertRaises(AccessError):
            self.Place.with_user(user).load_bundle(self.dir)

    def test_a_broken_bundle_is_refused(self):
        self.write(places=[PLACES[1], PLACES[0]] + PLACES[2:])   # a child before its parent
        with self.assertRaises(bundle.BundleError):
            self.load()
        self.write(postcodes=[('1234567890', 'zz-bazaar', 'import', '0')])   # a whole post code
        with self.assertRaises(bundle.BundleError):
            self.load()
        self.write()
        with open(os.path.join(self.dir, 'places.csv'), 'a', encoding='utf-8') as handle:
            handle.write('zz-sneak,دزدکی,,city,zz-land,True,,,test\n')          # an unsealed edit
        with self.assertRaises(bundle.BundleError):
            self.load()

    # --------------------------------------------------------------- responder
    def test_the_responder_is_told_how_to_rank_and_when_to_reload(self):
        spec = json.loads(self.env['ir.config_parameter'].sudo().get_param(SPEC_PARAM))
        self.assertEqual(spec, json.loads(json.dumps(tree.spec())))
        self.env.cr.execute("""SELECT c.relname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
                                WHERE t.tgname = 'place_graph_notify' ORDER BY 1""")
        self.assertEqual([row[0] for row in self.env.cr.fetchall()],
                         ['place_alias', 'place_link', 'place_node', 'place_postcode'])
        self.assertTrue(NOTIFY_CHANNEL)
        # and it reads the spec through a view that shows nothing else of the parameters
        self.env.cr.execute("SELECT value FROM place_responder_spec")
        self.assertEqual([json.loads(row[0]) for row in self.env.cr.fetchall()], [spec])
