# Part of iKiKu. Licensed under AGPL-3.0.
"""Where a person can work, from what they used to say. See ikiku_base 19.0.0.1.5."""
from odoo.addons.ikiku_base.tools.place_migration import move_table


def migrate(cr, version):
    if not version:
        return
    move_table(cr, 'ikiku_availability', 'ikiku.availability')
