# Part of iKiKu. Licensed under AGPL-3.0.
"""Mapping the old province and city onto the place tree, for the 2026-09-18 migrations.

It lives here rather than in a migration folder because three modules need it -- a person in
ikiku_base, a café and a need in ikiku_demand, an availability in ikiku_supply -- and each
runs its own script after its own tables have changed shape.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)
SNAPSHOT = 'ikiku_place_migration_20260918'


# A place's name is a translated field, so the column holds JSON, not text: matching it means
# asking whether ANY translation says this. Written once here, because getting it wrong
# fails loudly in the middle of a migration and quietly nowhere else.
NAME_IS = "EXISTS (SELECT 1 FROM jsonb_each_text({column}) AS t(lang, value) WHERE t.value = %s)"


def province_id(cr, province_name):
    """The place of the province an old row named, or None."""
    if not province_name:
        return None
    cr.execute("SELECT id FROM place_node WHERE kind = 'province' AND %s LIMIT 1"
               % NAME_IS.format(column='name'), ('استان %s' % province_name.strip(),))
    found = cr.fetchone()
    return found[0] if found else None


def place_for(cr, province_name, city_name):
    """(place id, how it was found) for an old province and city, or (None, reason).

    A city of that name INSIDE that province wins; a city of that name anywhere is next,
    because a province typed by hand is likelier to be wrong than a city; the province itself
    is the fallback, since «somewhere in Tehran province» is true and «nowhere» is not.
    """
    province = province_id(cr, province_name)
    if city_name and city_name.strip():
        cr.execute("""
            SELECT n.id,
                   (%s IS NOT NULL AND n.parent_path LIKE '%%/' || %s || '/%%') AS inside
              FROM place_node n
             WHERE n.kind IN ('city', 'village') AND {name_is}
          ORDER BY inside DESC, n.id
             LIMIT 1
        """.format(name_is=NAME_IS.format(column='n.name')),
            (province, str(province or 0), city_name.strip()))
        found = cr.fetchone()
        if found:
            return found[0], 'city in province' if found[1] else 'city'
    if province:
        return province, 'province'
    return None, 'no match'


def move_table(cr, table, model):
    """Set the place of every row of `table` from the snapshot, through the ORM.

    Through the ORM on purpose: a place written straight into the column would leave the city,
    the province and the public face of that record computed from the place it USED to have,
    and nothing would ever ask them again. There are a few dozen rows; correctness is worth
    more here than a single UPDATE.
    """
    cr.execute("SELECT to_regclass(%s)", (SNAPSHOT,))
    if not cr.fetchone()[0]:
        return 0, 0
    cr.execute("SELECT res_id, province_name, city_name FROM %s WHERE source_table = %%s"
               % SNAPSHOT, (table,))
    rows = cr.fetchall()
    env = api.Environment(cr, SUPERUSER_ID, {})
    records = env[model].with_context(tracking_disable=True, active_test=False)
    moved = empty = 0
    for res_id, province_name, city_name in rows:
        record = records.browse(res_id).exists()
        if not record:
            continue
        place_id, _how = place_for(cr, province_name, city_name)
        if place_id and not record.place_id:
            record.write({'place_id': place_id})
            moved += 1
        elif not place_id and not record.place_hint:
            # What they wrote is kept where a person can read it and ask them again.
            record.write({'place_hint': ' '.join(filter(None, (province_name, city_name))) or False})
            empty += 1
    _logger.info("place migration: %s -> %d placed, %d left empty", table, moved, empty)
    return moved, empty
