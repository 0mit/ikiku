# Part of place_graph. Licensed under AGPL-3.0.
"""Anything that is somewhere: one field to set, the rest read off the tree.

A model inherits this and gains `place_id` -- the finest place whoever filled the form
actually named. Everything else is read from the tree above it and stored, so a query can
group by city or filter by province without walking anything:

    class Business(models.Model):
        _inherit = ['my.business', 'place.located']
        _place_public_kinds = ('neighbourhood', 'district', 'city', 'village')

`place_public_id` is the point of that last line. A place can be finer than what a record
may show the world: a café names its street, and the page says the neighbourhood. Each model
states how coarse its public face is, and `place_public_id` is that place -- the nearest one
at or above `place_id` of a kind the model allows. Nothing has to remember the rule at the
template, and no template can get it wrong.

`place_hint` is for what the tree could not answer: a place somebody named that is not in
it. It is kept verbatim, beside the nearest place they could pick, rather than bent into a
row that nearly fits.
"""
from odoo import api, fields, models

# How much of its place a record shows, chosen per record. «city» is the default everywhere:
# the owner of the record widens it to their neighbourhood, nobody else does. The model's own
# _place_public_kinds is still the ceiling -- a choice can make a face coarser, never finer
# than the model allows.
PLACE_VISIBILITY = [('city', "فقط شهر"), ('neighbourhood', "محله")]
VISIBLE_KINDS = {
    'city': ('city', 'village', 'county', 'province', 'country'),
    'neighbourhood': ('neighbourhood', 'district', 'city', 'village', 'county', 'province', 'country'),
}


class PlaceLocated(models.AbstractModel):
    _name = 'place.located'
    _description = "Somewhere"

    # Which kinds this model may show publicly, finest first. The default shows whatever was
    # picked; a model with something to protect narrows it.
    _place_public_kinds = ('street', 'neighbourhood', 'district', 'city', 'village',
                           'county', 'province', 'country')

    place_id = fields.Many2one('place.node', string="جا", index=True, ondelete='restrict')
    place_visibility = fields.Selection(
        PLACE_VISIBILITY, string="چه چیزی از جا دیده شود", default='city', required=True,
        help="پیش‌فرض فقط شهر است؛ صاحبِ رکورد می‌تواند محله را هم نشان دهد.")
    place_hint = fields.Char(
        "جا، همان‌طور که نوشته شد",
        help="اگر جای گفته‌شده در درختِ جاها نبود، همان‌طور که نوشته شده می‌ماند.")
    place_path = fields.Char("نشانیِ کوتاه", related='place_id.path', store=True, readonly=True)
    place_city_id = fields.Many2one('place.node', string="شهر", compute='_compute_place_parts',
                                    store=True, index=True)
    place_province_id = fields.Many2one('place.node', string="استان", compute='_compute_place_parts',
                                        store=True, index=True)
    place_city_name = fields.Char(
        "شهر (نام)", compute='_compute_place_parts', store=True,
        help="نامِ شهر به‌صورتِ متن. نامِ جا میدانی چندزبانه است و کپیِ مستقیمش در ستون، "
             "JSON می‌شود؛ این همان نام است، خوانده‌شده به زبانِ جاری.")
    place_public_id = fields.Many2one(
        'place.node', string="جا، برای نمایشِ عمومی", compute='_compute_place_parts', store=True,
        help="درشت‌ترین جایی که این مدل اجازه دارد عمومی نشان دهد؛ از همین درخت خوانده می‌شود.")

    @api.depends('place_id', 'place_id.parent_id', 'place_id.kind', 'place_visibility')
    def _compute_place_parts(self):
        for record in self:
            place = record.place_id
            record.place_city_id = place.place_of_kinds(('city', 'village'))
            record.place_city_name = record.place_city_id.name or False
            record.place_province_id = place.place_of_kinds(('province',))
            record.place_public_id = place.place_of_kinds(record._place_public_kinds_of())

    def _place_public_kinds_of(self):
        """The kinds THIS record may show publicly: what its owner chose (place_visibility),
        never finer than the model allows (_place_public_kinds)."""
        wanted = VISIBLE_KINDS.get(self._place_visibility_of(), VISIBLE_KINDS['city'])
        return tuple(kind for kind in self._place_public_kinds if kind in wanted)

    def _place_visibility_of(self):
        """Whose choice decides this record's face. Its own; a model that belongs to another
        (a need to its business) answers with the owner's."""
        return self.place_visibility

    def place_distance_km(self, other):
        """Roughly how far apart two located records are, or False when either has no point."""
        self.ensure_one()
        here, there = self.place_id, other.place_id if other else None
        if not here or not there:
            return False
        return here.distance_km(there)
