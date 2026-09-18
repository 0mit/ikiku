#!/usr/bin/env python3
# Part of place_graph. Licensed under AGPL-3.0.
"""Turn an OpenStreetMap extract into place_graph rows.

    python3 osm_import.py iran-latest.osm.pbf --out addons/place_ir/data --cache /tmp/passes.pickle

It writes a place BUNDLE (bundle.py): places.csv, aliases.csv, links.csv and a sealed
manifest.json. Odoo takes it in with place_graph's bulk loader; the place responder serves it
as it is. This is a TOOL, not part of the running module: Odoo never imports it, and nothing on
a server needs osmium or shapely.

WHAT IT TAKES FROM THE MAP
  - administrative areas, by level, kept only where they lie inside the country asked for,
    so an extract that spills over a border does not bring a neighbour's provinces with it;
  - places mapped as a single point (most villages, many neighbourhoods) when no boundary
    exists for them;
  - names people also use: a former name, another spelling, an official name, the square,
    the metro stop -- as aliases, which are searched and never shown.

WHAT IT DECIDES
  - the tree, by asking which boundary a place sits inside, smallest first, so the hierarchy
    comes from the map rather than from a name that looks like it should be a parent;
  - the graph, by asking which boundaries touch: adjacency is the map's, not a guess.

LICENCE. OpenStreetMap data is © OpenStreetMap contributors, licensed ODbL 1.0. A database
derived from it carries that licence: the bundle this writes is such a database, and its
manifest says so, as does the module that ships it. The code here is AGPL-3.0,
like the rest of place_graph.
"""
import argparse
import csv
import logging
import os
import pickle
import re
import unicodedata
from collections import defaultdict

import osmium
import shapely

import bundle  # noqa: E402  (a sibling: this runs as a script, outside Odoo)
import tree as tree_rules  # noqa: E402
from shapely.geometry import shape
from shapely.strtree import STRtree

_logger = logging.getLogger('osm_import')

# OSM admin_level -> our kind, as Iran's mappers use the levels. A level whose meaning is
# settled decides on its own; the two that are not are marked and read below, because at
# those levels the same number carries a city, a rural district and a village.
IR_LEVELS = {
    '2': 'country', '4': 'province', '5': 'county', '6': 'county',
    '7': 'settlement', '8': 'settlement', '9': 'district', '10': 'settlement',
    '11': 'neighbourhood',
}
# A level-7 or level-8 area is a place; which kind it is, its own tags say. Iran's rural
# districts (دهستان) are the layer villages hang off: real, and nobody picks one.
RURAL_DISTRICT_PREFIX = 'دهستان'
SETTLEMENT_DEFAULT = {'7': 'city', '8': 'village', '10': 'neighbourhood'}
# Written as «شهر تهران» in the register and «تهران» by everybody. The register word is
# dropped from the name and kept as an alias, so both find it and only one is read out.
CITY_WORD = 'شهر'
# «منطقه ۶ شهر تهران» is «منطقه ۶» once you already know the city, which a path says anyway.
DISTRICT_OF_WORDS = ('شهر', 'شهرداری')
# A layer of city administration nobody says out loud. Kept, and left out of the path.
UNSAID_PREFIXES = ('ناحیه',)
STREET_WORDS = ('خیابان', 'بلوار', 'میدان', 'بزرگراه', 'کوچه', 'جاده', 'شهرک')
# place=* on a node or an area, when it says more than the level does.
PLACE_KINDS = {
    'city': 'city', 'town': 'city', 'municipality': 'city',
    'village': 'village', 'hamlet': 'village', 'isolated_dwelling': 'village', 'farm': 'village',
    'borough': 'district', 'city_district': 'district',
    'suburb': 'neighbourhood', 'quarter': 'neighbourhood', 'neighbourhood': 'neighbourhood',
}
# Kinds nobody picks or reads: real rows that hold their children and stay out of the path.
UNSHOWN_KINDS = {'country', 'county'}
# Which kinds are worth a neighbour graph: where "near" means anything to a person who has
# to get there. Two villages 40 km apart are not neighbours in any sense that helps.
LINKED_KINDS = {'neighbourhood', 'district', 'city'}
NEAR_SIBLINGS = 3            # nearest siblings joined when a place has no boundary
NEAR_LIMIT_KM = 4.0          # and only when they are this close
ALIAS_TAGS = {'old_name': 'old', 'alt_name': 'colloquial', 'official_name': 'colloquial',
              'loc_name': 'colloquial', 'name:fa': 'spelling', 'short_name': 'colloquial',
              'nat_name': 'colloquial', 'reg_name': 'colloquial'}
SQUARE_PLACES = {'square'}
# Names a school starts with. Matched at the START only: «قلعه مدرسه» is a village.
SCHOOL_START = re.compile(r'^(دبستان|دبیرستان|هنرستان|مدرسه|آموزشگاه|پیش ?دبستانی|مهد ?کودک)[\s\u200c]')
# Streets people name a place by. A residential lane is not one of them: at that size the
# name says an address, and an address is not a place anybody else needs to find.
STREET_CLASSES = {'trunk', 'primary', 'secondary', 'tertiary'}
STATION_TAGS = (('railway', 'station'), ('railway', 'halt'), ('public_transport', 'station'))
DEGREE_KM = 111.0            # close enough for "is this village next to that one"

SLUG_KEEP = re.compile(r'[^a-z0-9]+')
# The same folding search_suggest does, in miniature: this tool runs outside Odoo, and two
# names that differ by a ZWNJ or an Arabic ی must still compare equal here.
FOLD = str.maketrans({'ي': 'ی', 'ى': 'ی', 'ك': 'ک', 'ة': 'ه', 'ۀ': 'ه', 'أ': 'ا', 'إ': 'ا',
                      'آ': 'ا', 'ٱ': 'ا', 'ؤ': 'و', '\u200c': ' ', '\u064b': None})


def fold(text):
    return ' '.join((text or '').translate(FOLD).split())


def strip_word(name, word):
    """«شهر قزوین» -> «قزوین», keeping the name's own spelling otherwise."""
    parts = (name or '').split(' ', 1)
    return parts[1].strip() if len(parts) == 2 and fold(parts[0]) == word else name


def said_name(name):
    """The name as people say it, for comparing two rows: no «خیابان», no «شهر».

    Both register words have to go before two names are compared, and this runs BEFORE the
    names themselves are shortened -- «شهر تهران» the city and «تهران» the label node inside
    it are the same place, and comparing the written forms would miss that."""
    return fold(strip_word(street_name(name), CITY_WORD))


def street_name(name):
    """«خیابان فلسطین» -> «فلسطین»: the name people say, without the word for the thing."""
    for word in STREET_WORDS:
        stripped = strip_word(name, word)
        if stripped != name:
            return stripped
    return name


def district_name(name, parent):
    """«منطقه ۶ شهر تهران» -> «منطقه ۶»: the city is in the path already."""
    while parent is not None:
        if parent['kind'] in ('city', 'village'):
            for word in DISTRICT_OF_WORDS:
                for city in {parent['name'], strip_word(parent['name'], CITY_WORD)}:
                    tail = ' %s %s' % (word, city)
                    if name.endswith(tail):
                        return name[:-len(tail)].strip()
            break
        parent = parent['parent']
    return name


def without_word(name, *words):
    """A name with a leading register word removed: «شهر قزوین» -> «قزوین»."""
    folded = fold(name)
    for word in words:
        if folded.startswith(word + ' '):
            return folded[len(word) + 1:].strip()
    return folded


def slug(text):
    """A code a person can read in a URL: Latin, lower case, hyphens."""
    if not text:
        return ''
    text = unicodedata.normalize('NFKD', text)
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))
    return SLUG_KEEP.sub('-', text.lower()).strip('-')


class Collector:
    """One pass over the file per kind of thing, because each needs different machinery."""

    def __init__(self, path, levels):
        self.path = path
        self.levels = levels
        self.wkb = osmium.geom.WKBFactory()
        self.areas = []        # {'key', 'name', 'name_en', 'kind', 'level', 'geom', 'tags'}
        self.points = []       # {'key', 'name', 'name_en', 'kind', 'geom', 'tags'}
        self.landmarks = []    # {'name', 'kind', 'geom'}  -- squares, stations, renamed streets
        self.admin = {}        # osm relation id -> tags, including boundaries that did not close
        self.streets = []      # {'key', 'name', 'kind', 'geom', 'tags'} -- named, navigable streets

    # ------------------------------------------------------------------ passes
    def read_areas(self):
        processor = osmium.FileProcessor(self.path).with_areas()
        for obj in processor:
            if not isinstance(obj, osmium.osm.Area):
                continue
            tags = dict(obj.tags)
            name, level = tags.get('name'), tags.get('admin_level')
            if not name or tags.get('boundary') != 'administrative' or level not in self.levels:
                continue
            geom = self._geometry(obj)
            if geom is None:
                continue
            kind = self._kind(level, tags, name)
            key = '%s%d' % ('w' if obj.from_way() else 'r', obj.orig_id())
            self.areas.append({'key': key, 'name': name, 'kind': kind,
                               'name_en': tags.get('name:en'), 'level': level, 'geom': geom,
                               'tags': tags})
        _logger.info("areas: %d", len(self.areas))

    def _kind(self, level, tags, name):
        """What an administrative area IS. The level decides wherever the level is clear:
        a تهران منطقه tagged place=suburb is a district of a city, not a neighbourhood, and
        reading the tag instead would bury Tehran's twenty-two of them."""
        mapped = self.levels[level]
        if mapped != 'settlement':
            return mapped
        if fold(name).startswith(RURAL_DISTRICT_PREFIX):
            return 'county'                      # دهستان: villages hang off it, nobody picks it
        return PLACE_KINDS.get(tags.get('place') or '') or SETTLEMENT_DEFAULT.get(level, 'city')

    def read_admin_relations(self):
        """The tags of every administrative relation, whether or not its boundary closed.

        An extract is cut at the border, and a boundary cut in half does not assemble into
        an area. Without this pass such a place simply is not there, and everything inside
        it is silently dropped -- which is how a whole province goes missing."""
        for relation in osmium.FileProcessor(self.path, osmium.osm.RELATION):
            tags = dict(relation.tags)
            if tags.get('boundary') == 'administrative' and tags.get('name'):
                self.admin[relation.id] = tags
        _logger.info("administrative relations: %d", len(self.admin))

    def read_points(self):
        processor = osmium.FileProcessor(self.path, osmium.osm.NODE)
        for node in processor:
            tags = dict(node.tags)
            name = tags.get('name')
            place = tags.get('place')
            if name and place in PLACE_KINDS:
                self.points.append({'key': 'n%d' % node.id, 'name': name, 'name_en': tags.get('name:en'),
                                    'kind': PLACE_KINDS[place], 'tags': tags,
                                    'geom': shapely.Point(node.location.lon, node.location.lat)})
            elif name and (place in SQUARE_PLACES
                           or any(tags.get(key) == value for key, value in STATION_TAGS)):
                self.landmarks.append({'name': name, 'kind': 'square' if place in SQUARE_PLACES else 'transit',
                                       'geom': shapely.Point(node.location.lon, node.location.lat)})
        _logger.info("points: %d, landmarks: %d", len(self.points), len(self.landmarks))

    def read_streets(self):
        """Named streets, because a city is said in street names.

        «کجا؟» is answered with «فلسطین» far more often than with the name of the
        neighbourhood it runs through, and the street that was renamed is still called
        «کاخ». So a street of the classes people navigate by becomes a place of its own,
        under whatever contains it, and its former name becomes its alias. A residential
        lane does not: that is an address, and addresses are nobody else's business."""
        processor = osmium.FileProcessor(self.path, osmium.osm.NODE | osmium.osm.WAY).with_locations()
        for way in processor:
            if not isinstance(way, osmium.osm.Way):
                continue
            tags = dict(way.tags)
            name = tags.get('name')
            if tags.get('highway') not in STREET_CLASSES or not name:
                continue
            try:
                middle = way.nodes[len(way.nodes) // 2].location
                point = shapely.Point(middle.lon, middle.lat)
            except (osmium.InvalidLocationError, IndexError):
                continue
            self.streets.append({'key': 'w%d' % way.id, 'name': name, 'name_en': tags.get('name:en'),
                                 'kind': 'street', 'tags': tags, 'geom': point})
        _logger.info("streets: %d", len(self.streets))

    # ------------------------------------------------------------------- cache
    def save(self, path):
        """Keep the passes: reading a country extract takes minutes, and the decisions
        made afterwards are the part worth trying again."""
        with open(path, 'wb') as handle:
            pickle.dump({'areas': self.areas, 'points': self.points, 'landmarks': self.landmarks,
                         'admin': self.admin, 'streets': self.streets}, handle, protocol=4)

    def load(self, path):
        with open(path, 'rb') as handle:
            data = pickle.load(handle)
        self.areas, self.points, self.landmarks = data['areas'], data['points'], data['landmarks']
        self.admin = data.get('admin', {})
        self.streets = data.get('streets', [])
        _logger.info("from cache: %d streets", len(self.streets))
        _logger.info("from cache: %d areas, %d points, %d landmarks",
                     len(self.areas), len(self.points), len(self.landmarks))

    def _geometry(self, area):
        try:
            return shapely.from_wkb(bytes.fromhex(self.wkb.create_multipolygon(area)))
        except Exception:
            return None


def build(collector, iso, country_name, out_dir, keep_villages=True):
    """Everything inside the country's own provinces, as a tree and a graph.

    The country's own boundary is NOT used: a national extract is cut at the border and its
    outline often will not close, while the provinces inside it always do. So the provinces
    are the roots, the country is a row above them that carries no geometry, and "inside the
    country" means "inside one of its provinces" -- which is the same thing and is true of
    the file we actually have."""
    areas, points = list(collector.areas), list(collector.points)
    code_prefix = '%s-' % iso
    provinces = [a for a in areas if a['kind'] == 'province'
                 and (a['tags'].get('ISO3166-2') or '').startswith(code_prefix)]
    if not provinces:
        raise SystemExit("the extract has no %s province with an ISO3166-2 code" % iso)

    country = {'key': 'country-%s' % iso.lower(), 'name': country_name, 'name_en': iso,
               'kind': 'country', 'tags': {}, 'geom': None, 'is_point': False, 'parent': None}

    # A province whose boundary was cut by the extract never became an area. It is still a
    # province, and everything inside it is still in the country, so it is rebuilt as a row
    # without geometry and the counties that fell outside every province are given to it.
    # That is only sound while exactly one province is missing; with two there is no way to
    # tell whose counties are whose, and this stops rather than guess.
    assembled = {area['key'] for area in provinces}
    missing = [tags for osm_id, tags in collector.admin.items()
               if tags.get('admin_level') == '4'
               and (tags.get('ISO3166-2') or '').startswith(code_prefix)
               and ('r%d' % osm_id) not in assembled]
    if len(missing) > 1:
        raise SystemExit("%d provinces have no boundary in this extract (%s); a bigger extract "
                         "is needed, or they must be added by hand"
                         % (len(missing), ', '.join(t.get('name', '?') for t in missing)))
    incomplete = None
    if missing:
        tags = missing[0]
        incomplete = {'key': 'province-%s' % (tags['ISO3166-2'].lower()), 'name': tags['name'],
                      'name_en': tags.get('name:en'), 'kind': 'province', 'tags': tags,
                      'geom': None, 'is_point': False, 'parent': country}
        _logger.warning("no boundary for %s; its counties are attached to it by elimination",
                        tags.get('name'))
    _logger.info("provinces of %s: %d assembled, %d rebuilt", iso, len(provinces), len(missing))

    province_tree = STRtree([p['geom'] for p in provinces])

    def in_provinces(geom):
        point = geom if geom.geom_type == 'Point' else geom.representative_point()
        return any(provinces[index]['geom'].contains(point) for index in province_tree.query(point))

    orphan_counties = [a for a in areas if a['kind'] == 'county' and not in_provinces(a['geom'])] \
        if incomplete else []
    universe = [p['geom'] for p in provinces] + [c['geom'] for c in orphan_counties]
    universe_tree = STRtree(universe)

    def within_country(geom):
        point = geom if geom.geom_type == 'Point' else geom.representative_point()
        return any(universe[index].contains(point) for index in universe_tree.query(point))

    areas = [a for a in areas if a['kind'] != 'country' and within_country(a['geom'])]
    points = [p for p in points if within_country(p['geom'])]
    streets = [w for w in collector.streets if within_country(w['geom'])]
    if not keep_villages:
        points = [p for p in points if p['kind'] != 'village']
    _logger.info("inside %s: %d areas, %d points", country_name, len(areas), len(points))

    # ------------------------------------------------------------------- the tree
    # A place belongs to the SMALLEST boundary that contains it: the map decides the
    # hierarchy, not a name that reads like a parent.
    for area in areas:
        area['is_point'] = False
    for item in points + streets:
        item['is_point'] = True
    province_keys = {p['key'] for p in provinces}
    orphan_keys = {c['key'] for c in orphan_counties}
    ranked = sorted(areas, key=lambda a: a['geom'].area)
    tree = STRtree([a['geom'] for a in ranked])
    everything = []
    for item in ranked + points + streets:
        point = item['geom'] if item['is_point'] else item['geom'].representative_point()
        parent = None
        for index in tree.query(point):
            candidate = ranked[index]
            if candidate is item or not candidate['geom'].contains(point):
                continue
            if candidate['geom'].area <= (0 if item['is_point'] else item['geom'].area):
                continue
            if parent is None or candidate['geom'].area < parent['geom'].area:
                parent = candidate
        if parent is None and not item['is_point']:
            # Nothing larger holds it. An island that IS its county (جزیره خارک, whose
            # province boundary the extract does not assemble) has the county's outline: the
            # same outline one kind coarser is its parent, rather than no province at all.
            # Only here, for a place that would otherwise be a root -- elsewhere two equal
            # outlines are the map's business, not this tool's.
            for index in tree.query(point):
                candidate = ranked[index]
                if (candidate is not item and candidate['geom'].contains(point)
                        and candidate['geom'].area == item['geom'].area
                        and tree_rules.FINENESS.get(candidate['kind'], 4)
                        < tree_rules.FINENESS.get(item['kind'], 4)):
                    parent = candidate
                    break
        if item['key'] in province_keys:
            parent = country
        elif item['key'] in orphan_keys:
            parent = incomplete
        item['parent'] = parent
        everything.append(item)
    everything.insert(0, country)
    if incomplete:
        everything.insert(1, incomplete)

    # A place mapped as a point inside its own boundary is the boundary's label, not a
    # second place: «فلسطین» inside «فلسطین» is one neighbourhood written twice.
    # A place mapped as a point inside a place of the same name is that place written twice:
    # the label node «کرج» sits inside the neighbourhood «جهانشهر», inside the city «کرج», so
    # the match has to be looked for all the way up and not only at the parent.
    folded_in = {}
    for item in everything:
        if not item['is_point']:
            continue
        own = said_name(item['name'])
        ancestor = item['parent']
        while ancestor is not None:
            if not ancestor['is_point'] and said_name(ancestor['name']) == own:
                folded_in[item['key']] = ancestor
                break
            ancestor = ancestor['parent']
    if folded_in:
        everything = [item for item in everything if item['key'] not in folded_in]
        for item in everything:
            if item['parent'] is not None and item['parent']['key'] in folded_in:
                item['parent'] = folded_in[item['parent']['key']]
        _logger.info("points and streets folded into the place of the same name: %d", len(folded_in))

    # A school mapped as a settlement is a school: «دبستان دخترانه کوثر» tagged place=village
    # inside امیدیه is not a village anybody lives in, and offering it as one put schools among
    # the suggestions (the operator, 2026-09-18). A village point whose name BEGINS with a
    # school word and that lies inside a city becomes a landmark of the place that holds it --
    # its name still leads there. A settlement that merely contains the word («قلعه مدرسه»,
    # «کردبستان») or a mapped neighbourhood called «هنرستان» is a place and stays one.
    schools = {}
    for item in everything:
        if not (item['is_point'] and item['kind'] == 'village' and SCHOOL_START.match(item['name'] or '')):
            continue
        ancestor = item['parent']
        while ancestor is not None and ancestor['kind'] not in ('city', 'province', 'country'):
            ancestor = ancestor['parent']
        if ancestor is not None and ancestor['kind'] == 'city':
            schools[item['key']] = item
    if schools:
        everything = [item for item in everything if item['key'] not in schools]
        _logger.info("schools mapped as villages, kept as landmarks: %d", len(schools))

    # One row per street name per place: a street is mapped in dozens of pieces, and «فلسطین»
    # is one street whichever piece of it you stand on.
    kept_streets, seen_streets = [], set()
    for street in streets:
        if street['key'] in folded_in or street['parent'] is None:
            continue
        if street['parent']['kind'] not in ('city', 'district', 'neighbourhood'):
            continue          # a road between towns is not a place inside one
        key = (said_name(street['name']), street['parent']['key'])
        if key in seen_streets:
            continue
        seen_streets.add(key)
        street['name'] = street_name(street['name'])
        kept_streets.append(street)
    dropped = {s['key'] for s in streets} - {s['key'] for s in kept_streets}
    everything = [item for item in everything if item['key'] not in dropped]
    streets = kept_streets
    _logger.info("streets kept: %d", len(streets))

    surviving = {item['key'] for item in everything}
    areas = [area for area in areas if area['key'] in surviving]
    points = [point for point in points if point['key'] in surviving]

    # «شهر قزوین» is how a register writes it and «قزوین» is how it is said. The register
    # form stays as an alias, so both find it and only one is read out.
    register_aliases = []
    for item in everything:
        if item['kind'] in ('city', 'village'):
            short = strip_word(item['name'], CITY_WORD)
            if short != item['name']:
                register_aliases.append((item, item['name'], 'spelling'))
                item['name'] = short
        elif item['kind'] == 'district':
            short = district_name(item['name'], item['parent'])
            if short != item['name']:
                register_aliases.append((item, item['name'], 'spelling'))
                item['name'] = short
        if fold(item['name']).startswith(UNSAID_PREFIXES):
            item['unsaid'] = True

    # ------------------------------------------------------------------- the codes
    used = set()
    prefix = iso.lower()
    for item in everything:
        base = slug(item['name_en']) or slug(item['name']) or item['key']
        code = '%s-%s' % (prefix, base) if base else item['key']
        suffix = 1
        while code in used:
            suffix += 1
            code = '%s-%s-%d' % (prefix, base, suffix)
        used.add(code)
        item['code'] = code
        item['xmlid'] = 'place_%s' % item['key']

    # ------------------------------------------------------------------ the graph
    links = []
    bounded = [a for a in areas if a['kind'] in LINKED_KINDS]
    if bounded:
        geoms = [a['geom'] for a in bounded]
        touching = STRtree(geoms)
        for index, area in enumerate(bounded):
            for other_index in touching.query(area['geom']):
                other = bounded[other_index]
                if other_index <= index or other['kind'] != area['kind']:
                    continue
                if area['geom'].intersects(other['geom']) and not area['geom'].equals(other['geom']):
                    links.append((area, other, 'adjacent'))
    siblings = defaultdict(list)
    for item in points:
        if item['kind'] in LINKED_KINDS and item['parent'] is not None:
            siblings[item['parent']['key']].append(item)
    for group in siblings.values():
        for item in group:
            near = sorted(((other, item['geom'].distance(other['geom'])) for other in group
                           if other is not item), key=lambda pair: pair[1])[:NEAR_SIBLINGS]
            for other, distance in near:
                if distance * DEGREE_KM <= NEAR_LIMIT_KM:
                    links.append((item, other, 'near'))

    # ----------------------------------------------------------------- the aliases
    aliases = list(register_aliases)
    for item in everything:
        for tag, kind in ALIAS_TAGS.items():
            value = item['tags'].get(tag)
            if value and fold(value) != fold(item['name']):
                aliases.append((item, value, kind))
    # «کاخ» was the name of the street «فلسطین» is now: when the street became part of a
    # place of the same name, what it used to be called goes with it.
    for key, parent in folded_in.items():
        tags = next((item['tags'] for item in list(collector.points) + list(collector.streets)
                     if item['key'] == key), {})
        for tag, kind in ALIAS_TAGS.items():
            value = tags.get(tag)
            if value and fold(value) != fold(parent['name']):
                aliases.append((parent, value, kind))
    # A landmark lends its name to the smallest place that contains it.
    holders = [a for a in areas if a['kind'] in ('neighbourhood', 'district', 'city')]
    if holders:
        holder_tree = STRtree([h['geom'] for h in holders])
        for landmark in collector.landmarks:
            best = None
            for index in holder_tree.query(landmark['geom']):
                holder = holders[index]
                if not holder['geom'].contains(landmark['geom']):
                    continue
                if best is None or holder['geom'].area < best['geom'].area:
                    best = holder
            if best is None:
                continue
            if landmark['kind'] == 'old' and landmark.get('street_name') != fold(best['name']):
                continue   # an old name only travels with the thing the place is named after
            if fold(landmark['name']) != fold(best['name']):
                aliases.append((best, landmark['name'], landmark['kind']))

    for school in schools.values():
        aliases.append((school['parent'], school['name'], 'landmark'))

    write(everything, aliases, links, out_dir, country=iso)


def parents_first(places):
    """Places ordered so that nothing is written before the place it is inside.

    The loader creates rows in batches and resolves a parent by its xmlid, so a child that
    arrives first has nothing to point at. Depth decides the order, and a place whose parent
    somehow is not in the set is written as a root rather than dropped."""
    by_key = {place['key']: place for place in places}
    depth = {}

    def depth_of(place):
        if place['key'] in depth:
            return depth[place['key']]
        depth[place['key']] = 0          # guards a cycle the map should not contain
        parent = place['parent']
        found = 1 + depth_of(by_key[parent['key']]) if parent and parent['key'] in by_key else 0
        depth[place['key']] = found
        return found

    for place in places:
        depth_of(place)
    return sorted(places, key=lambda place: (depth[place['key']], place['key']))


def write(places, aliases, links, out_dir, country='ir'):
    """The places as a BUNDLE (bundle.py): places, aliases and links keyed by code, parents
    first, sealed with checksums and the OpenStreetMap licence. What Odoo, the responder and
    anybody else read, with no step in between."""
    places = parents_first(places)
    os.makedirs(out_dir, exist_ok=True)
    rows = []
    for place in places:
        point = None if place['geom'] is None else (
            place['geom'] if place['geom'].geom_type == 'Point'
            else place['geom'].representative_point())
        rows.append({
            'code': place['code'], 'name': place['name'], 'name_en': place['name_en'] or '',
            'kind': place['kind'], 'parent': place['parent']['code'] if place['parent'] else '',
            'in_path': 'False' if (place['kind'] in UNSHOWN_KINDS or place.get('unsaid')) else 'True',
            'latitude': round(point.y, 6) if point else '', 'longitude': round(point.x, 6) if point else '',
            'source': 'osm:%s' % place['key']})
    bundle.write_csv(os.path.join(out_dir, 'places.csv'), bundle.FILES['places.csv'], rows)
    seen, alias_rows = set(), []
    for place, name, kind in aliases:
        if (place['code'], name) in seen:
            continue
        seen.add((place['code'], name))
        alias_rows.append({'place': place['code'], 'name': name, 'kind': kind, 'source': 'osm'})
    bundle.write_csv(os.path.join(out_dir, 'aliases.csv'), bundle.FILES['aliases.csv'], alias_rows)
    pairs, link_rows = set(), []
    for one, other, relation in links:
        key = tuple(sorted((one['code'], other['code'])))
        if key in pairs:
            continue
        pairs.add(key)
        link_rows.append({'place': one['code'], 'other': other['code'], 'relation': relation, 'source': 'osm'})
    bundle.write_csv(os.path.join(out_dir, 'links.csv'), bundle.FILES['links.csv'], link_rows)
    bundle.seal(out_dir, sources=[bundle.OSM_SOURCE], country=country.lower())
    bundle.check(bundle.read(out_dir))
    _logger.info("bundle written: %d places, %d aliases, %d links", len(rows), len(alias_rows), len(link_rows))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('extract', help="an .osm.pbf file")
    parser.add_argument('--iso', default='IR',
                        help="the country's ISO 3166-1 code; its provinces carry it as ISO3166-2")
    parser.add_argument('--country-name', default="ایران", help="what to call the country row")
    parser.add_argument('--cache', help="keep the three reading passes here and reuse them")
    parser.add_argument('--out', required=True, help="directory for the CSV files")
    parser.add_argument('--no-villages', action='store_true', help="leave villages out")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')

    collector = Collector(args.extract, IR_LEVELS)
    if args.cache and os.path.exists(args.cache):
        collector.load(args.cache)
    else:
        collector.read_areas()
        collector.read_admin_relations()
        collector.read_points()
        collector.read_streets()
        if args.cache:
            collector.save(args.cache)
    build(collector, args.iso, args.country_name, args.out,
          keep_villages=not args.no_villages)


if __name__ == '__main__':
    main()
