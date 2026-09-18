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

from odoo.addons.place_graph.models.place import LOADING, ORIGINS
from odoo.addons.place_graph.tools.tree import ALIAS_KINDS as KINDS

# What a bundle says about an alias. A person changing one of these on an imported alias
# takes it over; deleting one archives it, so the next load cannot bring it back.
BUNDLE_FIELDS = ('name', 'kind', 'active')


class PlaceAlias(models.Model):
    _name = 'place.alias'
    _description = "Another name for a place"
    _order = 'place_id, kind, name'

    place_id = fields.Many2one('place.node', string="Place", required=True,
                               ondelete='cascade', index=True)
    name = fields.Char("Also called", required=True, translate=True)
    kind = fields.Selection(KINDS, string="Kind", required=True, default='colloquial')
    source = fields.Char("Source", help="Who says so -- a register, an import, or a person.")
    active = fields.Boolean(default=True)
    origin = fields.Selection(ORIGINS, string="Origin", required=True, default='overlay', index=True)
    bundle_key = fields.Char("Bundle key", index=True, readonly=True, copy=False,
                             help="«place code|name» as the bundle wrote it; how a load finds "
                                  "this row again after a person renamed it.")
    kept_fields = fields.Char("Kept by a person", readonly=True, copy=False)

    _alias_uniq = models.Constraint('UNIQUE(place_id, name)',
                                    "A place carries a given alias once.")

    @api.constrains('name')
    def _check_name(self):
        for alias in self:
            if not (alias.name or '').strip():
                raise ValidationError("An alias needs a name.")

    def init(self):
        super().init()
        self.env['place.node']._place_notify_on(self._table)

    def write(self, vals):
        if not self.env.context.get(LOADING):
            _keep(self, vals, BUNDLE_FIELDS)
        return super().write(vals)

    def unlink(self):
        """An imported alias a person removes is archived, not deleted: deleted, the next
        bundle load would find it missing and write it back."""
        if self.env.context.get(LOADING):
            return super().unlink()
        imported = self.filtered(lambda alias: alias.origin == 'bundle')
        imported.write({'active': False})
        return super(PlaceAlias, self - imported).unlink()


def _keep(records, vals, carried):
    """Write the carried fields a person is changing into `kept_fields` of imported rows."""
    touched = [name for name in carried if name in vals]
    if not touched:
        return
    for record in records.filtered(lambda r: r.origin == 'bundle'):
        kept = set(filter(None, (record.kept_fields or '').split(',')))
        if not kept.issuperset(touched):
            models.Model.write(record, {'kept_fields': ','.join(sorted(kept.union(touched)))})
