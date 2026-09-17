# Part of iKiKu. Licensed under AGPL-3.0.
"""Keep the old province and city before the columns become something else.

Until 2026-09-18 a place was an `ikiku.province` row and a line of free text. Now it is one
row of the place tree, and the two columns that held the old answer are reused: province_id
points at a place, and city is read off it. So the old values have to be read BEFORE the
schema changes -- which is here, in the first module's pre-migrate -- and are mapped to
places afterwards, each module for its own tables.

The snapshot is left behind on purpose. If a row could not be matched to a place, the only
record of what it used to say is this table, and dropping it would throw that away.
"""
SNAPSHOT = 'ikiku_place_migration_20260918'
# table -> (province column, city column)
SOURCES = {
    'res_partner': ('ikiku_province_id', 'ikiku_city'),
    'ikiku_demand': ('province_id', 'city'),
    'ikiku_business': ('province_id', 'city'),
    'ikiku_availability': ('province_id', 'city'),
}


def migrate(cr, version):
    if not version:
        return
    cr.execute("SELECT to_regclass('ikiku_province')")
    if not cr.fetchone()[0]:
        return          # nothing to keep: this database never had the old model
    cr.execute("""
        CREATE TABLE IF NOT EXISTS %s (
            source_table varchar, res_id integer, province_name varchar, city_name varchar)
    """ % SNAPSHOT)
    for table, (province_column, city_column) in SOURCES.items():
        cr.execute("SELECT to_regclass(%s)", (table,))
        if not cr.fetchone()[0]:
            continue
        cr.execute("""
            INSERT INTO {snapshot} (source_table, res_id, province_name, city_name)
            SELECT %s, t.id, p.name, t.{city}
              FROM {table} t
         LEFT JOIN ikiku_province p ON p.id = t.{province}
             WHERE t.{province} IS NOT NULL OR t.{city} IS NOT NULL
        """.format(snapshot=SNAPSHOT, table=table, province=province_column, city=city_column),
            (table,))
