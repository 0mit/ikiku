# Part of iKiKu. Licensed under AGPL-3.0.
"""Point every person at a place in the tree, and retire the old model. See tools/place_migration."""
from odoo.addons.ikiku_base.tools.place_migration import move_table


def migrate(cr, version):
    if not version:
        return
    move_table(cr, 'res_partner', 'res.partner')
    # The old ikiku.province table is dropped last, by ikiku_portal: the other modules still
    # have foreign keys into it at this point, and they are only re-pointed when each of them
    # is updated in turn.
