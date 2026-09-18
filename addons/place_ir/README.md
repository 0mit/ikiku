# Places of Iran

Iran's places for [place_graph](../place_graph): provinces, counties, cities, villages,
city districts, neighbourhoods and the named streets people give directions by. It also has
the other names a place answers to, and which places touch which.

## What is in `data/`

A **place bundle** (`place_graph/tools/bundle.py`): `places.csv`, `aliases.csv`, `links.csv`
and a sealed `manifest.json` holding the files' checksums, the source and its licence, and the
ranking spec. Everything is keyed by `code`, never by a database id or an xmlid.

## Where it comes from

    python3 ../place_graph/tools/osm_import.py iran-latest.osm.pbf \
        --out data --cache /tmp/passes.pickle

The extract is Geofabrik's `asia/iran-latest.osm.pbf`. The tool needs `osmium` and `shapely`,
and it runs outside Odoo; nothing on a server needs either. It writes the bundle directly, and
a rebuild from the same extract is byte-for-byte the same files. `python3
../place_graph/tools/bundle.py check data` checks one without loading it.

Map data © OpenStreetMap contributors, licensed under the **Open Database Licence (ODbL)
1.0** — <https://www.openstreetmap.org/copyright>. The files under `data/` are a derived
database and carry that licence. The code is AGPL-3.0. A page that shows these places has to
credit OpenStreetMap. What other sources could add, and what each would oblige, is in
[SOURCES.md](SOURCES.md).

## Loading

`data/place_ir_data.xml` calls place_graph's bulk loader on install and on every update of
this module:

- **install**: the whole bundle in about 20 seconds (it was two minutes through the ORM);
- **update, bundle unchanged**: the stored fingerprint matches and nothing is read;
- **update, bundle changed**: only the difference is written. A place the bundle dropped is
  archived, because records point at it.
- **never** over what staff decided: places, aliases and post codes they added or ratified
  (origin `overlay`), and fields they changed on an imported place (`kept_fields`).

To take a regenerated bundle in, deploy it with `-u place_ir`. Staff can also run
`env['place.node'].load_country_data()`, which forces a load.
