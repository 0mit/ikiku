# Part of iKiKu. Licensed under AGPL-3.0.
"""Give databases installed before `sequence` existed the province order.

The province records are noupdate, so the install-time <function> that orders
them never runs on an existing database; this applies the same order once.
"""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    api.Environment(cr, SUPERUSER_ID, {})['ikiku.province']._ikiku_apply_order()
