# Part of place_graph. Licensed under AGPL-3.0.
"""Post code prefixes, so a code can suggest a place -- and the code itself is never kept.

A full Iranian post code is ten digits and names one building. That is an address: it
belongs to nobody but the person who typed it. So this model stores a PREFIX only, never
more than PREFIX_LENGTH digits, and `prefix_of` is the one door the digits come through.
Callers pass the whole code, get a place back, and keep the place.

Two sources, and the difference is stated in the row rather than guessed by a reader:
  import   a table loaded from outside. It covers a lot and is right about most of it.
  learned  people who typed a code here and confirmed the place it belongs to. It covers
           only where we are, and it is right about exactly that.
  staff    a person here decided. It wins over both.

`hits` counts confirmations, so a learned row earns its place over an imported one that
disagrees, once enough people say the same thing.
"""
from odoo import api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.search_suggest.tools import text as suggest_text

PREFIX_LENGTH = 5          # never store more of a post code than this
LEARNED_OVER_IMPORT = 3    # confirmations before what people say beats what the table says
SOURCES = [('staff', "Decided here"), ('learned', "Learned from people"), ('import', "Imported table")]
TRUST = {'staff': 2, 'learned': 1, 'import': 0}


class PlacePostcode(models.Model):
    _name = 'place.postcode'
    _description = "Post code prefix of a place"
    _order = 'prefix, id'

    prefix = fields.Char("Prefix", required=True, size=PREFIX_LENGTH, index=True)
    place_id = fields.Many2one('place.node', string="Place", required=True,
                               ondelete='cascade', index=True)
    source = fields.Selection(SOURCES, string="Source", required=True, default='import')
    hits = fields.Integer("Confirmations", default=0)

    _prefix_place_uniq = models.Constraint('UNIQUE(prefix, place_id)',
                                           "One row per prefix and place.")

    @api.constrains('prefix')
    def _check_prefix(self):
        for row in self:
            if not (row.prefix or '').isdigit() or len(row.prefix) != PREFIX_LENGTH:
                raise ValidationError("A post code prefix is %s digits." % PREFIX_LENGTH)

    # ------------------------------------------------------------------- reading
    @api.model
    def prefix_of(self, code):
        """The first PREFIX_LENGTH digits of a code, in Latin digits, or False.

        This is where a whole post code stops. Nothing downstream sees the rest of it."""
        digits = ''.join(ch for ch in suggest_text.normalize(code or '') if ch.isdigit())
        return digits[:PREFIX_LENGTH] if len(digits) >= PREFIX_LENGTH else False

    @api.model
    def place_for_code(self, code):
        """The place a post code points at: what staff said, else what people say once
        enough of them agree, else the imported table. Empty when nothing is known."""
        prefix = self.prefix_of(code)
        rows = self.sudo().search([('prefix', '=', prefix)]) if prefix else self.browse()
        if not rows:
            return self.env['place.node'].browse()
        best = max(rows, key=lambda row: (TRUST[row.source] if row.source != 'learned'
                                          else (1 if row.hits >= LEARNED_OVER_IMPORT else -1),
                                          row.hits))
        return best.place_id

    # ------------------------------------------------------------------ learning
    @api.model
    def learn(self, code, place):
        """Record that somebody's code belongs to `place`. The code is not kept."""
        prefix = self.prefix_of(code)
        if not prefix or not place:
            return self.browse()
        row = self.sudo().search([('prefix', '=', prefix), ('place_id', '=', place.id)], limit=1)
        if row:
            row.hits += 1
            return row
        return self.sudo().create({'prefix': prefix, 'place_id': place.id,
                                   'source': 'learned', 'hits': 1})
