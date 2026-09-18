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

from odoo.addons.place_graph.models.alias import _keep
from odoo.addons.place_graph.models.place import LOADING, ORIGINS

RELATIONS = [('adjacent', "Borders it"), ('near', "Near it")]
MIRRORING = 'place_link_mirroring'   # set while the mirror row is being written
BUNDLE_FIELDS = ('relation', 'active')


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
    active = fields.Boolean(default=True)
    origin = fields.Selection(ORIGINS, string="Origin", required=True, default='overlay', index=True)
    bundle_key = fields.Char("Bundle key", index=True, readonly=True, copy=False,
                             help="«code|code» of the pair, smaller first, as the bundle wrote it.")
    kept_fields = fields.Char("Kept by a person", readonly=True, copy=False)

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
        if not self.env.context.get(LOADING) and not self.env.context.get(MIRRORING):
            _keep(self, vals, BUNDLE_FIELDS)
        result = super().write(vals)
        if not self.env.context.get(MIRRORING):
            self._mirror()
        return result

    def unlink(self):
        if not self.env.context.get(LOADING) and not self.env.context.get(MIRRORING):
            # An imported pair a person removes is archived, both ways round, so a bundle load
            # cannot write it back.
            imported = self.filtered(lambda link: link.origin == 'bundle')
            imported.write({'active': False})
            self -= imported
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
            existing = mirroring.with_context(active_test=False).search(
                [('place_id', '=', link.other_id.id), ('other_id', '=', link.place_id.id)], limit=1)
            values = {'relation': link.relation, 'source': link.source, 'active': link.active,
                      'origin': link.origin, 'bundle_key': link.bundle_key,
                      'kept_fields': link.kept_fields}
            if existing:
                existing.write(values)
            else:
                mirroring.create(dict(values, place_id=link.other_id.id, other_id=link.place_id.id))
