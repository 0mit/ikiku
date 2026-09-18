# Part of iKiKu. Licensed under AGPL-3.0.
"""Order the places already loaded: by kind, then the cities people name most.

The data file runs this on install only -- a `<function>` inside `noupdate` is skipped on an
update, which is what keeps an order staff changed later from being overwritten. A database
that already has the tree therefore needs this once, here.
"""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    if not version:
        return
    api.Environment(cr, SUPERUSER_ID, {})['place.node']._ikiku_apply_place_order()
