# Part of place_graph. Licensed under AGPL-3.0.
"""Mark what was imported before bundles existed, so the first bundle load finds it.

Until 19.0.1.1.0 the places were loaded through the ORM and nothing said which rows were the
map's and which were a person's. The new `origin` column arrives filled with its default,
'overlay' -- which would tell every future load to keep its hands off everything. The rows
the OpenStreetMap import wrote say so in `source`; they are the bundle's, and they are given
the key a bundle load matches on. Anything else stays the overlay.
"""


def migrate(cr, version):
    if not version:
        return
    cr.execute("UPDATE place_node SET origin = 'bundle' WHERE source LIKE 'osm:%'")
    cr.execute("""
        UPDATE place_alias a SET origin = 'bundle', bundle_key = n.code || '|' || (a.name->>'en_US')
          FROM place_node n
         WHERE n.id = a.place_id AND a.source = 'osm'
    """)
    cr.execute("""
        UPDATE place_link l SET origin = 'bundle',
               -- "C": byte order, which is what the loader sorts by in Python
               bundle_key = LEAST(p.code COLLATE "C", o.code COLLATE "C") || '|' || GREATEST(p.code COLLATE "C", o.code COLLATE "C")
          FROM place_node p, place_node o
         WHERE p.id = l.place_id AND o.id = l.other_id AND l.source = 'osm'
    """)
