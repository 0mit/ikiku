{
    'name': "Places of Iran",
    'summary': "Iran's provinces, counties, cities, villages, districts, neighbourhoods and "
               "named streets, with what else people call them.",
    'description': """
Places of Iran
==============

Data, not code: one row per place, loaded into place_graph.

* 31 provinces, their counties (kept, never shown), cities and villages, the districts of
  the cities that have them, neighbourhoods, and the named streets people give directions by.
* What else a place is called: a former name, another spelling, the square or the metro stop
  inside it. «کاخ» finds «فلسطین», and «فلسطین» is what is shown.
* Which places touch which, so «نزدیکِ اینجا» can be answered.

The files are loaded once, by the install hook, and again on demand with
`env['place.node'].load_country_data()` -- not as manifest data, because Odoo re-reads a data
file on every update and this is a hundred thousand rows.

SOURCE AND LICENCE. Made from an OpenStreetMap extract of Iran with
place_graph/tools/osm_import.py. Map data © OpenStreetMap contributors, available under the
Open Database Licence (ODbL) 1.0: https://www.openstreetmap.org/copyright. The CSV files in
data/ are a derived database and carry that licence; the code is AGPL-3.0. Anything built on
them has to keep saying both.

WHAT IS NOT PROMISED. A map is never finished. Boundaries that the extract cut in half do
not assemble, so a province may have to be rebuilt from its counties (Bushehr, at the time
of writing), and a district mapped inside a historic town sits under that town rather than
under the city. Where iKiKu works, places are checked by hand; elsewhere they are as good as
the map is.
    """,
    'author': "شرکت تعاونی ایکیکو",
    'website': "https://ikiku.ir",
    'category': 'Hidden/Tools',
    'version': '19.0.1.0.0',
    'license': 'AGPL-3',
    'depends': ['place_graph'],
    'post_init_hook': 'post_init_hook',
    'installable': True,
}
