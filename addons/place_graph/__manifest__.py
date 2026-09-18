{
    'name': "Places: a searchable graph",
    'summary': "Provinces, cities, districts and neighbourhoods as one tree and one graph, "
               "found by what people call them.",
    'description': """
Places
======

Somewhere to put a place, once, so every model that needs one points at the same row.

* One tree: country, province, county, city, district, neighbourhood. A layer nobody picks
  (a county between a province and a city) is kept for correctness and left out of the path
  with `in_path`.
* One graph beside it: neighbouring places, symmetric by construction, either because their
  borders touch or because they are close enough to mean.
* Aliases that are searched and never shown: the old name, the square, the metro stop, the
  landmark -- «کاخ» finds فلسطین, and the answer still reads فلسطین.
* Search is search_suggest's: the place's own names count fully, aliases below them,
  the places above it lower, its neighbours lowest, and a `within` place lifts what is
  inside it, so «فلسطین» typed in Tehran means the one in Tehran.
* Post code prefixes, never whole post codes: a full code names one building and is nobody's
  business but theirs. Prefixes come from a table and from what people confirm.
* A country's places arrive as a BUNDLE (tools/bundle.py): files made outside Odoo, checked,
  checksummed, and taken in with COPY -- a hundred thousand places in seconds, an update as
  its difference. Rows are the source's (origin 'bundle') or decided here (origin 'overlay').
* Every change to the place tables is announced (NOTIFY place_graph_changed) with the ranking
  spec published beside it, so a search service outside Odoo can hold the places in memory
  and rank exactly as this module does (services/place_responder).

Nothing here is about one country: the tree, the kinds and the graph are the same
everywhere, and a country's own places are data.
    """,
    'author': "شرکت تعاونی ایکیکو",
    'website': "https://ikiku.ir",
    'category': 'Hidden/Tools',
    'version': '19.0.1.1.0',
    'license': 'AGPL-3',
    'depends': ['search_suggest'],
    'data': [
        'security/place_groups.xml',
        'security/ir.model.access.csv',
        'views/place_views.xml',
    ],
    'installable': True,
}
