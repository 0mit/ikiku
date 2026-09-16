# Part of iKiKu. Licensed under AGPL-3.0.
"""Give databases installed before the signup tiles their order and everyday names.

The spec data is noupdate, so the install-time <function> that writes them never
runs on an existing database; this applies the same values once.
"""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    api.Environment(cr, SUPERUSER_ID, {})['ikiku.spec.node']._ikiku_apply_labels()
