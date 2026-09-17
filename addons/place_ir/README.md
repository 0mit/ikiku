# Places of Iran

Iran's places for [place_graph](../place_graph): provinces, counties, cities, villages,
city districts, neighbourhoods and the named streets people give directions by — with the
other names a place answers to, and which places touch which.

## Where the data comes from

    python3 ../place_graph/tools/osm_import.py iran-latest.osm.pbf \
        --out data --cache /tmp/passes.pickle

The extract is Geofabrik's `asia/iran-latest.osm.pbf`. The tool needs `osmium` and
`shapely`; nothing on a server does.

Map data © OpenStreetMap contributors, licensed under the **Open Database Licence (ODbL)
1.0** — <https://www.openstreetmap.org/copyright>. The three CSV files under `data/` are a
derived database and carry that licence. The code is AGPL-3.0. A page that shows these
places has to credit OpenStreetMap.

## Loading

The install hook loads the files once. After regenerating them:

    env['place.node'].load_country_data()

Rows are keyed by the xmlid in the `id` column, so loading again updates instead of
duplicating.
