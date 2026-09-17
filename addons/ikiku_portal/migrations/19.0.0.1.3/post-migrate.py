# Part of iKiKu. Licensed under AGPL-3.0.
"""Retire ikiku.province, once nothing points at it any more.

This runs last of the five modules, which is the only moment the old table has no foreign
keys left: each of the others re-pointed its own location column at place.node as it was
updated. What the rows said is in ikiku_place_migration_20260918, which is kept.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute("SELECT to_regclass('ikiku_province')")
    if not cr.fetchone()[0]:
        return
    cr.execute("""
        SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE c.relkind = 'r' AND n.nspname = 'public' AND c.relname LIKE '%ikiku_province%'
    """)
    tables = [row[0] for row in cr.fetchall()]
    for table in tables:
        # CASCADE removes foreign keys INTO the old table, never a column of another table.
        cr.execute('DROP TABLE IF EXISTS "%s" CASCADE' % table)
    _logger.info("place migration: dropped %s", ", ".join(tables) or "nothing")
