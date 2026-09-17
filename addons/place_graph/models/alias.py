# Part of place_graph. Licensed under AGPL-3.0.
"""What else a place is called: searched, never shown.

People do not name a place the way a register does. They say the old name, the square at
its corner, the metro stop, the hospital, the bazaar -- «کاخ» for فلسطین, years after the
street was renamed. An alias is how that reaches the right place.

It is a search key and nothing else. Lists, cards and paths show the place's own name, so
the alias never teaches anybody a name that is not the name -- it only makes theirs work.
"""
from odoo import api, fields, models
from odoo.exceptions import ValidationError

KINDS = [
    ('old', "Former name"),
    ('colloquial', "What people call it"),
    ('landmark', "Landmark inside it"),
    ('transit', "Metro or bus stop"),
    ('square', "Square or crossing"),
    ('spelling', "Another spelling"),
]


class PlaceAlias(models.Model):
    _name = 'place.alias'
    _description = "Another name for a place"
    _order = 'place_id, kind, name'

    place_id = fields.Many2one('place.node', string="Place", required=True,
                               ondelete='cascade', index=True)
    name = fields.Char("Also called", required=True, translate=True)
    kind = fields.Selection(KINDS, string="Kind", required=True, default='colloquial')
    source = fields.Char("Source", help="Who says so -- a register, an import, or a person.")

    _alias_uniq = models.Constraint('UNIQUE(place_id, name)',
                                    "A place carries a given alias once.")

    @api.constrains('name')
    def _check_name(self):
        for alias in self:
            if not (alias.name or '').strip():
                raise ValidationError("An alias needs a name.")
