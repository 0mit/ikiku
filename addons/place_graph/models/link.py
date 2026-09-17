# Part of place_graph. Licensed under AGPL-3.0.
"""Which places touch which, kept in both directions.

Adjacency is symmetric in the world, so it is symmetric here: writing one row writes its
mirror, and removing one removes the mirror. A graph that is symmetric only half the time
answers «چه جاهایی نزدیکِ اینجاست؟» differently depending on which side you ask from, and
the answer a person gets must not depend on that.

`relation` says how the two are close, because the two are found differently and a reader
has to be able to tell them apart:
  adjacent  their borders touch -- drawn from boundaries
  near      no shared border, but close enough to walk or to mean -- drawn from distance
"""
from odoo import api, fields, models
from odoo.exceptions import ValidationError

RELATIONS = [('adjacent', "Borders it"), ('near', "Near it")]
MIRRORING = 'place_link_mirroring'   # set while the mirror row is being written


class PlaceLink(models.Model):
    _name = 'place.link'
    _description = "Places that are neighbours"
    _order = 'place_id, relation, id'

    place_id = fields.Many2one('place.node', string="Place", required=True,
                               ondelete='cascade', index=True)
    other_id = fields.Many2one('place.node', string="Neighbour", required=True,
                               ondelete='cascade', index=True)
    relation = fields.Selection(RELATIONS, string="How", required=True, default='adjacent')
    source = fields.Char("Source")

    _pair_uniq = models.Constraint('UNIQUE(place_id, other_id)',
                                   "Two places are neighbours once.")

    @api.constrains('place_id', 'other_id')
    def _check_not_itself(self):
        for link in self:
            if link.place_id == link.other_id:
                raise ValidationError("A place is not its own neighbour.")

    @api.model_create_multi
    def create(self, vals_list):
        links = super().create(vals_list)
        if not self.env.context.get(MIRRORING):
            links._mirror()
        return links

    def write(self, vals):
        result = super().write(vals)
        if not self.env.context.get(MIRRORING):
            self._mirror()
        return result

    def unlink(self):
        if not self.env.context.get(MIRRORING):
            mirrors = self.search([('place_id', 'in', self.other_id.ids),
                                   ('other_id', 'in', self.place_id.ids)])
            pairs = {(link.other_id.id, link.place_id.id) for link in self}
            mirrors.filtered(lambda m: (m.place_id.id, m.other_id.id) in pairs) \
                   .with_context(**{MIRRORING: True}).unlink()
        return super().unlink()

    def _mirror(self):
        """Make sure the row the other way round exists and says the same."""
        mirroring = self.with_context(**{MIRRORING: True})
        for link in self:
            existing = mirroring.search([('place_id', '=', link.other_id.id),
                                         ('other_id', '=', link.place_id.id)], limit=1)
            values = {'relation': link.relation, 'source': link.source}
            if existing:
                existing.write(values)
            else:
                mirroring.create(dict(values, place_id=link.other_id.id, other_id=link.place_id.id))
