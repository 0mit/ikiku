#!/usr/bin/env python3
# Part of place_graph. Licensed under AGPL-3.0.
"""A place bundle: a country's places as plain files, made outside Odoo and read by anything.

WHY. Finding places is work that belongs outside the ERP: reading a map extract, asking
Wikidata, merging a gazetteer. It needs tools no server has (osmium, shapely), it takes
minutes, and it must be re-run when the sources change. What comes out of it has to be
something Odoo -- and anybody else -- can take in at once, without the tools. That is a
bundle: a directory of CSV files and a manifest that says what they are, where they came
from, under which licence, and what their checksums are.

    bundle/
      manifest.json   format, country, sources and licences, files with sha256 and rows,
                      and the ranking spec (tree.spec()) the responder ranks with
      places.csv      code,name,name_en,kind,parent,in_path,latitude,longitude,source
      aliases.csv     place,name,kind,source
      links.csv       place,other,relation,source          (one row per pair)
      postcodes.csv   prefix,place,source,hits             (optional; five digits, never more)

Every reference is by `code`, the one key that never changes meaning: not by a database id,
which differs between databases, and not by an xmlid, which only Odoo has.

    python3 bundle.py convert LEGACY_DIR OUT_DIR   # the old place.node.csv trio -> a bundle
    python3 bundle.py check BUNDLE                 # every rule below, and the checksums
    python3 bundle.py seal BUNDLE [--source ...]   # (re)write manifest.json after an edit
    python3 bundle.py digest BUNDLE                # the fingerprint a loader compares

The rules a bundle is checked against: codes unique; every parent, alias place, link end and
post code place exists; parents written before children; no cycle; kinds and alias kinds
from tree.py; a prefix is exactly five digits. A bundle that fails is never loaded.
"""
import argparse
import csv
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

try:
    from . import tree
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import tree  # noqa: E402

FORMAT = 'place-bundle/1'
POSTCODE_PREFIX = 5
FILES = {
    'places.csv': ['code', 'name', 'name_en', 'kind', 'parent', 'in_path', 'latitude',
                   'longitude', 'source'],
    'aliases.csv': ['place', 'name', 'kind', 'source'],
    'links.csv': ['place', 'other', 'relation', 'source'],
    'postcodes.csv': ['prefix', 'place', 'source', 'hits'],
}
REQUIRED = ('places.csv',)
RELATIONS = ('adjacent', 'near')
POSTCODE_SOURCES = ('import', 'learned', 'staff')


class BundleError(ValueError):
    """The bundle breaks a rule. The message names the file, the row and the rule."""


# ---------------------------------------------------------------------------- reading
def read_csv(path, header):
    with open(path, newline='', encoding='utf-8') as handle:
        reader = csv.reader(handle)
        found = next(reader, None)
        if found != header:
            raise BundleError("%s: header is %s, expected %s" % (os.path.basename(path), found, header))
        return [dict(zip(header, row)) for row in reader if row]


def read(directory, verify=True):
    """{'manifest': {...}, 'places': [...], 'aliases': [...], 'links': [...], 'postcodes': [...]}.

    With verify, the checksums in the manifest are checked first: a file that changed since
    the bundle was sealed is somebody's unsealed edit, and loading it would load a guess."""
    manifest_path = os.path.join(directory, 'manifest.json')
    if not os.path.exists(manifest_path):
        raise BundleError("%s: no manifest.json -- not a bundle" % directory)
    with open(manifest_path, encoding='utf-8') as handle:
        manifest = json.load(handle)
    if manifest.get('format') != FORMAT:
        raise BundleError("manifest format is %r, this reader knows %r" % (manifest.get('format'), FORMAT))
    out = {'manifest': manifest}
    for name, header in FILES.items():
        path = os.path.join(directory, name)
        key = name[:-4]
        if not os.path.exists(path):
            if name in REQUIRED:
                raise BundleError("%s is missing" % name)
            out[key] = []
            continue
        if verify:
            expected = manifest.get('files', {}).get(name, {}).get('sha256')
            if expected != sha256_of(path):
                raise BundleError("%s does not match its checksum in manifest.json; seal the "
                                  "bundle again if the edit was meant" % name)
        out[key] = read_csv(path, header)
    return out


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def digest(directory):
    """One fingerprint for the bundle's content: the checksums of its files, in order.

    A loader stores it and compares it on the next update, so an unchanged bundle costs a
    hash and nothing else. The manifest's own prose (dates, notes) is not part of it."""
    with open(os.path.join(directory, 'manifest.json'), encoding='utf-8') as handle:
        files = json.load(handle).get('files', {})
    canonical = json.dumps({name: files[name].get('sha256') for name in sorted(files)},
                           sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


# ---------------------------------------------------------------------------- checking
def check(data):
    """Raise BundleError on the first broken rule; return counts when all hold."""
    places = data['places']
    codes, parent_of = {}, {}
    for number, row in enumerate(places, start=2):
        code = row['code']
        if not code:
            raise BundleError("places.csv line %d: no code" % number)
        if code in codes:
            raise BundleError("places.csv line %d: code %s used twice" % (number, code))
        if not row['name'].strip():
            raise BundleError("places.csv line %d (%s): no name" % (number, code))
        if row['kind'] not in tree.KIND_CODES:
            raise BundleError("places.csv line %d (%s): kind %r is not one of %s"
                              % (number, code, row['kind'], ', '.join(tree.KIND_CODES)))
        if row['in_path'] not in ('True', 'False'):
            raise BundleError("places.csv line %d (%s): in_path is True or False" % (number, code))
        for axis in ('latitude', 'longitude'):
            if row[axis]:
                try:
                    float(row[axis])
                except ValueError:
                    raise BundleError("places.csv line %d (%s): %s %r is not a number"
                                      % (number, code, axis, row[axis])) from None
        if row['parent']:
            if row['parent'] not in codes:
                raise BundleError("places.csv line %d (%s): parent %s is not written above it"
                                  % (number, code, row['parent']))
            parent_of[code] = row['parent']
        codes[code] = number
    # Parents-first order already rules a cycle out: a parent has to be on an earlier line.
    seen_alias = set()
    for number, row in enumerate(data['aliases'], start=2):
        if row['place'] not in codes:
            raise BundleError("aliases.csv line %d: place %s is not in places.csv" % (number, row['place']))
        if row['kind'] not in tree.ALIAS_KIND_CODES:
            raise BundleError("aliases.csv line %d: kind %r" % (number, row['kind']))
        if not row['name'].strip():
            raise BundleError("aliases.csv line %d: no name" % number)
        if (row['place'], row['name']) in seen_alias:
            raise BundleError("aliases.csv line %d: %s is already called %s"
                              % (number, row['place'], row['name']))
        seen_alias.add((row['place'], row['name']))
    pairs = set()
    for number, row in enumerate(data['links'], start=2):
        for end in ('place', 'other'):
            if row[end] not in codes:
                raise BundleError("links.csv line %d: %s is not in places.csv" % (number, row[end]))
        if row['place'] == row['other']:
            raise BundleError("links.csv line %d: a place is not its own neighbour" % number)
        if row['relation'] not in RELATIONS:
            raise BundleError("links.csv line %d: relation %r" % (number, row['relation']))
        pair = tuple(sorted((row['place'], row['other'])))
        if pair in pairs:
            raise BundleError("links.csv line %d: %s and %s are already neighbours" % ((number,) + pair))
        pairs.add(pair)
    seen_prefix = set()
    for number, row in enumerate(data['postcodes'], start=2):
        prefix = row['prefix']
        if not (prefix.isdigit() and prefix.isascii() and len(prefix) == POSTCODE_PREFIX):
            raise BundleError("postcodes.csv line %d: a prefix is exactly %d Latin digits, never "
                              "a whole code" % (number, POSTCODE_PREFIX))
        if row['place'] not in codes:
            raise BundleError("postcodes.csv line %d: place %s is not in places.csv" % (number, row['place']))
        if row['source'] not in POSTCODE_SOURCES:
            raise BundleError("postcodes.csv line %d: source %r" % (number, row['source']))
        if (prefix, row['place']) in seen_prefix:
            raise BundleError("postcodes.csv line %d: %s -> %s twice" % (number, prefix, row['place']))
        seen_prefix.add((prefix, row['place']))
    return {'places': len(places), 'aliases': len(data['aliases']), 'links': len(data['links']),
            'postcodes': len(data['postcodes'])}


# ---------------------------------------------------------------------------- deriving
def derive(data, id_of=None):
    """What the model would compute for every place, from the bundle alone.

    Returns {code: {'path', 'suggest_index', 'parent_path'?}}. `parent_path` needs database
    ids, so it is only worked out when `id_of` (code -> id) is given. The rules are tree.py's,
    which the model uses too: a loaded row and an edited row read the same."""
    rows = {row['code']: row for row in data['places']}
    parent_of = {code: row['parent'] for code, row in rows.items() if row['parent']}
    aliases, neighbours = {}, {}
    for row in sorted(data['aliases'], key=lambda r: (r['place'], r['kind'], r['name'])):
        aliases.setdefault(row['place'], []).append((row['name'], row['kind']))
    for row in data['links']:
        neighbours.setdefault(row['place'], []).append((row['relation'], row['other']))
        neighbours.setdefault(row['other'], []).append((row['relation'], row['place']))
    out = {}
    for code, row in rows.items():
        above = [rows[key] for key in tree.chain(code, parent_of) if key in rows]
        own = (row['name'], row['kind'], row['in_path'] == 'True')
        path = tree.read_path(own, [(a['name'], a['kind'], a['in_path'] == 'True') for a in above])
        near = [rows[other]['name'] for _relation, other in sorted(neighbours.get(code, []),
                                                                   key=lambda item: item[0])]
        texts = tree.suggest_texts([row['name']], row['name_en'], row['code'],
                                   aliases.get(code, []), [a['name'] for a in above], near)
        derived = {'path': path, 'suggest_index': tree.suggest_index(texts)}
        if id_of is not None:
            ids = [id_of[a['code']] for a in reversed(above)] + [id_of[code]]
            derived['parent_path'] = ''.join('%d/' % i for i in ids)
        out[code] = derived
    return out


# ---------------------------------------------------------------------------- writing
def write_csv(path, header, rows):
    with open(path, 'w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle, lineterminator='\n')
        writer.writerow(header)
        for row in rows:
            writer.writerow([row.get(column, '') for column in header])


def seal(directory, sources=None, country=None, note=None):
    """Write manifest.json for the files that are there: checksums, row counts, the ranking
    spec. Sources and licences already in the manifest are kept unless new ones are given."""
    manifest_path = os.path.join(directory, 'manifest.json')
    manifest = {}
    if os.path.exists(manifest_path):
        with open(manifest_path, encoding='utf-8') as handle:
            manifest = json.load(handle)
    files = {}
    for name in FILES:
        path = os.path.join(directory, name)
        if os.path.exists(path):
            with open(path, encoding='utf-8') as handle:
                rows = sum(1 for _line in handle) - 1
            files[name] = {'sha256': sha256_of(path), 'rows': rows}
    manifest.update({
        'format': FORMAT,
        'sealed': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'files': files,
        'spec': tree.spec(),
    })
    if country:
        manifest['country'] = country
    if sources:
        manifest['sources'] = sources
    if note:
        manifest['note'] = note
    manifest.setdefault('sources', [])
    with open(manifest_path, 'w', encoding='utf-8') as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write('\n')
    return manifest


def convert(legacy_dir, out_dir):
    """The three Odoo-import CSV files (place.node.csv, place.alias.csv, place.link.csv) to a
    bundle. Their xmlids become codes; nothing else changes."""
    nodes = read_csv(os.path.join(legacy_dir, 'place.node.csv'),
                     ['id', 'name', 'name_en', 'code', 'kind', 'parent_id/id', 'in_path',
                      'latitude', 'longitude', 'source'])
    code_of = {row['id']: row['code'] for row in nodes}
    places = [{'code': row['code'], 'name': row['name'], 'name_en': row['name_en'], 'kind': row['kind'],
               'parent': code_of[row['parent_id/id']] if row['parent_id/id'] else '',
               'in_path': row['in_path'], 'latitude': row['latitude'], 'longitude': row['longitude'],
               'source': row['source']} for row in nodes]
    aliases = [{'place': code_of[row['place_id/id']], 'name': row['name'], 'kind': row['kind'],
                'source': row['source']}
               for row in read_csv(os.path.join(legacy_dir, 'place.alias.csv'),
                                   ['id', 'place_id/id', 'name', 'kind', 'source'])]
    links = [{'place': code_of[row['place_id/id']], 'other': code_of[row['other_id/id']],
              'relation': row['relation'], 'source': row['source']}
             for row in read_csv(os.path.join(legacy_dir, 'place.link.csv'),
                                 ['id', 'place_id/id', 'other_id/id', 'relation', 'source'])]
    os.makedirs(out_dir, exist_ok=True)
    write_csv(os.path.join(out_dir, 'places.csv'), FILES['places.csv'], places)
    write_csv(os.path.join(out_dir, 'aliases.csv'), FILES['aliases.csv'], aliases)
    write_csv(os.path.join(out_dir, 'links.csv'), FILES['links.csv'], links)
    return len(places), len(aliases), len(links)


OSM_SOURCE = {
    'name': 'OpenStreetMap',
    'licence': 'ODbL-1.0',
    'attribution': '© OpenStreetMap contributors',
    'url': 'https://www.openstreetmap.org/copyright',
    'how': 'place_graph/tools/osm_import.py over a Geofabrik extract',
}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)
    one = sub.add_parser('convert', help="the old Odoo-import CSV trio to a bundle")
    one.add_argument('legacy')
    one.add_argument('out')
    one.add_argument('--country', default='ir')
    sub.add_parser('check', help="check a bundle").add_argument('bundle')
    sealing = sub.add_parser('seal', help="write manifest.json for a bundle's files")
    sealing.add_argument('bundle')
    sealing.add_argument('--country')
    sealing.add_argument('--note')
    sub.add_parser('digest', help="print a bundle's fingerprint").add_argument('bundle')
    args = parser.parse_args(argv)

    if args.command == 'convert':
        counts = convert(args.legacy, args.out)
        seal(args.out, sources=[OSM_SOURCE], country=args.country,
             note="converted from the Odoo-import CSV files by bundle.py convert")
        print("%d places, %d aliases, %d links -> %s" % (counts + (args.out,)))
    elif args.command == 'check':
        counts = check(read(args.bundle))
        print(json.dumps(counts))
    elif args.command == 'seal':
        manifest = seal(args.bundle, country=args.country, note=args.note)
        check(read(args.bundle))
        print(json.dumps(manifest['files'], indent=1))
    elif args.command == 'digest':
        print(digest(args.bundle))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except BundleError as error:
        print("bundle: %s" % error, file=sys.stderr)
        sys.exit(1)

