# Part of place_graph. Licensed under AGPL-3.0.
"""Taking a bundle in: a hundred thousand places in seconds, and an update in less.

The ORM loads rows one model call at a time, recomputing each place's path and search index
as it goes, and on a hundred thousand places that was two minutes on a fast machine and far
longer on a one-core server -- paid by every install, every test run and every fresh
database. This loads the same rows with COPY and set-based UPDATEs, and works out the
computed columns with the functions the model itself uses (tools/tree.py), so a loaded row
and an edited row read exactly the same.

WHAT A LOAD MAY TOUCH. Rows are keyed by `code` (places) and `bundle_key` (aliases, links);
post code prefixes by (prefix, place) and only where `source` is 'import'.
  - a bundle row that is new is written;
  - a bundle row that changed is updated -- except the fields a person took over
    (`kept_fields`), which stay as that person left them;
  - a bundle row the new bundle no longer has is RETIRED: a place is archived, because
    records point at it; an alias, a link or an imported prefix is removed;
  - a row whose origin is 'overlay' -- decided here, by a person -- is never changed or
    retired by any bundle. That is the human-ratified layer, and it outranks the source.

WHEN. place_ir calls load_bundle() from its data file, so it runs on install and on every
update of place_ir; the bundle's fingerprint is stored, and an unchanged bundle costs one
hash. `force=True` loads regardless.

AFTER. What the ORM would have recomputed on other models -- the stored city, province and
public place of every record that is somewhere (place.located) -- is recomputed for the
records whose place actually changed, and nothing else.
"""
import io
import json
import logging
import time

from odoo import api, fields, models
from odoo.exceptions import AccessError

from odoo.addons.place_graph.models.place import LOADING, NOTIFY_CHANNEL
from odoo.addons.place_graph.tools import bundle as bundle_tool
from odoo.addons.place_graph.tools import tree

_logger = logging.getLogger(__name__)

PARAM = 'place_graph.bundle.%s'   # the fingerprint of the bundle last loaded, per country


def _copy(cr, table, columns, rows):
    """COPY rows into table. Values are text, None is NULL."""
    buffer = io.StringIO()
    for row in rows:
        buffer.write('\t'.join('\\N' if value is None else _escape(value) for value in row))
        buffer.write('\n')
    buffer.seek(0)
    cr.copy_expert('COPY %s (%s) FROM STDIN' % (table, ', '.join(columns)), buffer)


def _escape(value):
    if value is True:
        return 't'
    if value is False:
        return 'f'
    return str(value).replace('\\', '\\\\').replace('\t', '\\t').replace('\n', '\\n').replace('\r', '\\r')


def _number(text):
    return round(float(text), 6) if text not in (None, '') else None


def _kept(value):
    return set(filter(None, (value or '').split(',')))


def _translated(value, lang):
    """A translated jsonb column read the way the ORM reads it: the language asked for, else
    the source (en_US)."""
    if not value:
        return ''
    return value.get(lang) if lang in value else value.get('en_US', '')


class PlaceNode(models.Model):
    _inherit = 'place.node'

    @api.model
    def _bundle_sequence(self, kind, name):
        """The sequence a place the bundle adds starts with. A module that orders places
        (ikiku_base does) says so here; a row that is already there keeps its own."""
        return 100

    @api.model
    def load_bundle(self, directory, force=False):
        """Load the bundle in `directory`. Returns what happened, as counts."""
        if not (self.env.su or self.env.user.has_group('base.group_system')):
            raise AccessError("Only an administrator loads a bundle of places.")
        started = time.time()
        data = bundle_tool.read(directory)
        bundle_tool.check(data)
        fingerprint = bundle_tool.digest(directory)
        country = (data['manifest'].get('country') or 'xx').lower()
        params = self.env['ir.config_parameter'].sudo()
        if not force and params.get_param(PARAM % country) == fingerprint:
            _logger.info("place bundle %s: unchanged (%s), nothing to load", country, fingerprint[:12])
            return {'state': 'unchanged'}

        self.env.flush_all()
        cr = self.env.cr
        # One load at a time: two workers updating the same module must not both write.
        cr.execute("SELECT pg_advisory_xact_lock(hashtext('place_graph.load_bundle'))")
        loader = _Loader(self.with_context(**{LOADING: True}), data, '%s-' % country)
        summary = loader.run()
        params.set_param(PARAM % country, fingerprint)
        cr.execute("SELECT pg_notify(%s, 'bundle')", (NOTIFY_CHANNEL,))
        summary.update(state='loaded', seconds=round(time.time() - started, 1), country=country)
        _logger.info("place bundle %s: %s", country, summary)
        return summary

    @api.model
    def refresh_derived(self, ids=None):
        """Recompute path, parent_path and suggest_index in bulk, from the database as it is.
        Returns the ids whose values changed. Also a repair tool: run it after SQL surgery."""
        if not (self.env.su or self.env.user.has_group('base.group_system')):
            raise AccessError("Only an administrator rebuilds the places' computed columns.")
        self.env.flush_all()
        changed = _refresh_derived(self.env, ids)
        self.env.invalidate_all()
        return changed


class _Loader:
    """One load. Holds what is in the database and what the bundle says, and writes the
    difference."""

    def __init__(self, Place, data, prefix):
        self.Place = Place
        self.env = Place.env
        self.cr = Place.env.cr
        self.data = data
        self.prefix = prefix
        self.uid = Place.env.uid
        self.now = fields.Datetime.to_string(fields.Datetime.now())
        self.summary = {}
        self.touched = set()      # place ids whose own bundle fields changed

    # ------------------------------------------------------------------ places
    def places(self):
        cr = self.cr
        cr.execute("""SELECT id, code, name, name_en, kind, parent_id, in_path, latitude, longitude,
                             active, source, origin, kept_fields FROM place_node""")
        existing = {row[1]: row for row in cr.fetchall()}
        id_of = {code: row[0] for code, row in existing.items()}
        rows = self.data['places']
        new = [row for row in rows if row['code'] not in existing]
        if new:
            cr.execute("SELECT nextval('place_node_id_seq') FROM generate_series(1, %s)", (len(new),))
            for row, (new_id,) in zip(new, cr.fetchall()):
                id_of[row['code']] = new_id
        inserts, updates = [], []
        for row in rows:
            code = row['code']
            want = {
                'name': row['name'], 'name_en': row['name_en'] or None, 'kind': row['kind'],
                'parent_id': id_of[row['parent']] if row['parent'] else None,
                'in_path': row['in_path'] == 'True',
                'latitude': _number(row['latitude']), 'longitude': _number(row['longitude']),
                'active': True, 'source': row['source'] or None,
            }
            if code not in existing:
                inserts.append((id_of[code], code, want))
                continue
            (place_id, _code, name, name_en, kind, parent_id, in_path, latitude, longitude,
             active, source, origin, kept_fields) = existing[code]
            if origin != 'bundle':
                continue          # decided here: the bundle does not get a say
            have = {'name': (name or {}).get('en_US', ''), 'name_en': name_en, 'kind': kind,
                    'parent_id': parent_id, 'in_path': bool(in_path),
                    'latitude': _number(latitude), 'longitude': _number(longitude),
                    'active': bool(active), 'source': source}
            for field in _kept(kept_fields):
                if field in want:
                    want[field] = have[field]
            if want != have:
                updates.append((place_id, want))
                if any(want[f] != have[f] for f in ('name', 'kind', 'parent_id', 'in_path', 'active')):
                    self.touched.add(place_id)
        in_bundle = {row['code'] for row in rows}
        retired = [row[0] for code, row in existing.items()
                   if row[11] == 'bundle' and row[9] and code.startswith(self.prefix)
                   and code not in in_bundle and 'active' not in _kept(row[12])]

        if inserts:
            _copy(self.cr, 'place_node',
                  ['id', 'code', 'name', 'name_en', 'kind', 'parent_id', 'in_path', 'latitude',
                   'longitude', 'active', 'source', 'sequence', 'origin', 'create_uid', 'write_uid',
                   'create_date', 'write_date'],
                  [(place_id, code, _json({'en_US': w['name']}), w['name_en'], w['kind'], w['parent_id'],
                    w['in_path'], w['latitude'], w['longitude'], True, w['source'],
                    self.Place._bundle_sequence(w['kind'], w['name']), 'bundle', self.uid, self.uid,
                    self.now, self.now)
                   for place_id, code, w in inserts])
        if updates:
            cr.execute("""CREATE TEMP TABLE place_stage (id int, name text, name_en varchar, kind varchar,
                          parent_id int, in_path bool, latitude numeric, longitude numeric,
                          active bool, source varchar) ON COMMIT DROP""")
            _copy(self.cr, 'place_stage',
                  ['id', 'name', 'name_en', 'kind', 'parent_id', 'in_path', 'latitude', 'longitude',
                   'active', 'source'],
                  [(place_id, w['name'], w['name_en'], w['kind'], w['parent_id'], w['in_path'],
                    w['latitude'], w['longitude'], w['active'], w['source']) for place_id, w in updates])
            cr.execute("""
                UPDATE place_node p SET name = jsonb_set(COALESCE(p.name, '{}'::jsonb), '{en_US}', to_jsonb(s.name)),
                       name_en = s.name_en, kind = s.kind, parent_id = s.parent_id, in_path = s.in_path,
                       latitude = s.latitude, longitude = s.longitude, active = s.active, source = s.source,
                       write_uid = %s, write_date = now() at time zone 'UTC'
                  FROM place_stage s WHERE p.id = s.id""", (self.uid,))
        if retired:
            cr.execute("""UPDATE place_node SET active = false, write_uid = %s,
                          write_date = now() at time zone 'UTC' WHERE id = ANY(%s)""", (self.uid, retired))
            self.touched.update(retired)
        self.id_of = id_of
        self.summary.update(places_added=len(inserts), places_changed=len(updates),
                            places_retired=len(retired))

    # ----------------------------------------------------------------- aliases
    def aliases(self):
        cr = self.cr
        cr.execute("""SELECT id, place_id, name->>'en_US', kind, active, origin, bundle_key, kept_fields, source
                        FROM place_alias""")
        rows = cr.fetchall()
        by_key = {row[6]: row for row in rows if row[5] == 'bundle' and row[6]}
        taken = {(row[1], row[2]) for row in rows}
        inserts, updates, keys = [], [], set()
        for alias in self.data['aliases']:
            key = '%s|%s' % (alias['place'], alias['name'])
            keys.add(key)
            place_id = self.id_of[alias['place']]
            want = {'name': alias['name'], 'kind': alias['kind'], 'active': True,
                    'source': alias['source'] or None}
            if key not in by_key:
                if (place_id, alias['name']) not in taken:      # a person already has it
                    inserts.append((place_id, key, want))
                    taken.add((place_id, alias['name']))
                continue
            row = by_key[key]
            have = {'name': row[2], 'kind': row[3], 'active': bool(row[4]), 'source': row[8]}
            for field in _kept(row[7]):
                if field in want:
                    want[field] = have[field]
            if want != have:
                updates.append((row[0], want))
        removed = [row[0] for key, row in by_key.items()
                   if key not in keys and key.startswith(self.prefix) and not _kept(row[7])]
        if inserts:
            _copy(cr, 'place_alias',
                  ['place_id', 'name', 'kind', 'source', 'active', 'origin', 'bundle_key',
                   'create_uid', 'write_uid', 'create_date', 'write_date'],
                  [(place_id, _json({'en_US': w['name']}), w['kind'], w['source'], True, 'bundle', key,
                    self.uid, self.uid, self.now, self.now) for place_id, key, w in inserts])
        for alias_id, w in updates:
            cr.execute("""UPDATE place_alias SET name = jsonb_set(name, '{en_US}', to_jsonb(%s::text)),
                          kind = %s, active = %s, source = %s, write_date = now() at time zone 'UTC'
                          WHERE id = %s""", (w['name'], w['kind'], w['active'], w['source'], alias_id))
        if removed:
            cr.execute("DELETE FROM place_alias WHERE id = ANY(%s)", (removed,))
        self.summary.update(aliases_added=len(inserts), aliases_changed=len(updates),
                            aliases_removed=len(removed))

    # ------------------------------------------------------------------- links
    def links(self):
        cr = self.cr
        cr.execute("""SELECT id, place_id, other_id, relation, active, origin, bundle_key, kept_fields
                        FROM place_link""")
        rows = cr.fetchall()
        by_key = {}
        for row in rows:
            if row[5] == 'bundle' and row[6]:
                by_key.setdefault(row[6], []).append(row)
        taken = {(row[1], row[2]) for row in rows}
        inserts, updates, keys = [], [], set()
        for link in self.data['links']:
            one, other = sorted((link['place'], link['other']))
            key = '%s|%s' % (one, other)
            keys.add(key)
            want = {'relation': link['relation'], 'active': True}
            if key not in by_key:
                a, b = self.id_of[one], self.id_of[other]
                for pair in ((a, b), (b, a)):
                    if pair not in taken:
                        inserts.append(pair + (key, link['relation'], link['source'] or None))
                        taken.add(pair)
                continue
            for row in by_key[key]:
                have = {'relation': row[3], 'active': bool(row[4])}
                target = dict(want)
                for field in _kept(row[7]):
                    if field in target:
                        target[field] = have[field]
                if target != have:
                    updates.append((row[0], target))
        removed = [row[0] for key, group in by_key.items()
                   if key not in keys and key.startswith(self.prefix)
                   for row in group if not _kept(row[7])]
        if inserts:
            _copy(cr, 'place_link',
                  ['place_id', 'other_id', 'bundle_key', 'relation', 'source', 'active', 'origin',
                   'create_uid', 'write_uid', 'create_date', 'write_date'],
                  [(a, b, key, relation, source, True, 'bundle', self.uid, self.uid, self.now, self.now)
                   for a, b, key, relation, source in inserts])
        for link_id, w in updates:
            cr.execute("""UPDATE place_link SET relation = %s, active = %s,
                          write_date = now() at time zone 'UTC' WHERE id = %s""",
                       (w['relation'], w['active'], link_id))
        if removed:
            cr.execute("DELETE FROM place_link WHERE id = ANY(%s)", (removed,))
        self.summary.update(links_added=len(inserts) // 2, links_changed=len(updates),
                            links_removed=len(removed) // 2)

    # --------------------------------------------------------------- postcodes
    def postcodes(self):
        cr = self.cr
        cr.execute("SELECT id, prefix, place_id, source, hits FROM place_postcode")
        rows = cr.fetchall()
        imported = {(row[1], row[2]): row for row in rows if row[3] == 'import'}
        taken = {(row[1], row[2]) for row in rows}
        inserts, updates, keys = [], [], set()
        for code in self.data['postcodes']:
            key = (code['prefix'], self.id_of[code['place']])
            keys.add(key)
            hits = int(code['hits'] or 0)
            if key in imported:
                if imported[key][4] != hits:
                    updates.append((imported[key][0], hits))
            elif key not in taken:            # learned or decided here already: theirs wins
                inserts.append(key + (hits,))
                taken.add(key)
        in_country = set(self.id_of.values())
        removed = [row[0] for key, row in imported.items() if key not in keys and key[1] in in_country]
        if inserts:
            _copy(cr, 'place_postcode', ['prefix', 'place_id', 'source', 'hits', 'create_uid', 'write_uid',
                                         'create_date', 'write_date'],
                  [(prefix, place_id, 'import', hits, self.uid, self.uid, self.now, self.now)
                   for prefix, place_id, hits in inserts])
        for postcode_id, hits in updates:
            cr.execute("UPDATE place_postcode SET hits = %s WHERE id = %s", (hits, postcode_id))
        if removed:
            cr.execute("DELETE FROM place_postcode WHERE id = ANY(%s)", (removed,))
        self.summary.update(postcodes_added=len(inserts), postcodes_removed=len(removed))

    # ---------------------------------------------------------------------- all
    def run(self):
        self.places()
        self.aliases()
        self.links()
        self.postcodes()
        changed = _refresh_derived(self.env)
        self.summary['derived_changed'] = len(changed)
        self.env.invalidate_all(flush=False)
        _refresh_located(self.env, self.touched | set(changed))
        return self.summary


def _json(value):
    return json.dumps(value, ensure_ascii=False)


def _refresh_derived(env, ids=None):
    """path, parent_path and suggest_index of every place, from the database as it is now,
    by tree.py's rules; written only where they differ. Returns the ids that changed."""
    cr = env.cr
    lang = env.lang or 'en_US'
    langs = [code for code, _name in env['res.lang'].get_installed()] or [lang]
    name_langs = langs if len(langs) > 1 else [lang]
    cr.execute("""SELECT id, code, name, name_en, kind, parent_id, in_path, path, parent_path,
                         suggest_index FROM place_node""")
    nodes = {row[0]: row for row in cr.fetchall()}
    parent_of = {row[0]: row[5] for row in nodes.values() if row[5]}
    cr.execute("SELECT place_id, name, kind FROM place_alias WHERE active")
    aliases = {}
    for place_id, name, kind in cr.fetchall():
        aliases.setdefault(place_id, []).append((_translated(name, lang), kind))
    cr.execute("SELECT place_id, other_id, relation, id FROM place_link WHERE active ORDER BY relation, id")
    neighbours = {}
    for place_id, other_id, _relation, _id in cr.fetchall():
        neighbours.setdefault(place_id, []).append(other_id)
    wanted = set(ids) if ids else None
    changes = []
    for place_id, row in nodes.items():
        if wanted is not None and place_id not in wanted:
            continue
        name = _translated(row[2], lang)
        above = [nodes[key] for key in tree.chain(place_id, parent_of) if key in nodes]
        path = tree.read_path((name, row[4], bool(row[6])),
                              [(_translated(a[2], lang), a[4], bool(a[6])) for a in above])
        parent_path = ''.join('%d/' % a[0] for a in reversed(above)) + '%d/' % place_id
        own = sorted(aliases.get(place_id, []), key=lambda item: (item[1], item[0]))
        texts = tree.suggest_texts(
            [_translated(row[2], code) for code in name_langs], row[3], row[1], own,
            [_translated(a[2], lang) for a in above],
            [_translated(nodes[other][2], lang) for other in neighbours.get(place_id, []) if other in nodes])
        index = tree.suggest_index(texts)
        if (path, parent_path, index) != (row[7], row[8], row[9]):
            changes.append((place_id, path, parent_path, index))
    if changes:
        cr.execute("""CREATE TEMP TABLE place_derived (id int, path varchar, parent_path varchar,
                      suggest_index text) ON COMMIT DROP""")
        _copy(cr, 'place_derived', ['id', 'path', 'parent_path', 'suggest_index'], changes)
        cr.execute("""UPDATE place_node p SET path = d.path, parent_path = d.parent_path,
                      suggest_index = d.suggest_index FROM place_derived d WHERE p.id = d.id""")
        cr.execute("DROP TABLE place_derived")
    return [change[0] for change in changes]


def _refresh_located(env, place_ids):
    """Recompute what every located record stores from its place, for the places that
    changed. Nothing is recomputed for a record whose place did not move or rename."""
    if not place_ids:
        return
    ids = list(place_ids)
    for model_name in env.registry['place.located']._inherit_children:
        Model = env.registry[model_name]
        if Model._abstract or not Model._auto:
            continue
        records = env[model_name].sudo().with_context(active_test=False).search([('place_id', 'in', ids)])
        if records:
            records.modified(['place_id'])
            records.flush_recordset()
    env.flush_all()
