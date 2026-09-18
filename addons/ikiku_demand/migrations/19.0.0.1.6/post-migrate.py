# Part of iKiKu. Licensed under AGPL-3.0.
"""A café's place is public to its city unless its holder chooses its neighbourhood (2026-09-18).

Until now every café showed its neighbourhood without being asked. The new column arrives as
«city» for all of them, and what is stored as their public place -- and their needs' -- is
worked out again from it here, so no page keeps showing the old, finer place.
"""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    for model in ('ikiku.business', 'ikiku.demand'):
        records = env[model].with_context(active_test=False).search([('place_id', '!=', False)])
        records.modified(['place_visibility'])
    env.flush_all()
