# Part of place_graph. Licensed under AGPL-3.0.
"""Places as one tree plus one graph, searched the way people say them.

A place is a node: a country, a province, a county, a city, a district or a neighbourhood.
`parent_id` makes the tree; `link_ids` makes the graph beside it, because what a person
means by "near" does not follow the tree -- two neighbourhoods on either side of a border
street are neighbours, and their districts are not.

Three things this file exists for:

  1. The tree may carry steps a person never picks. An official hierarchy has layers that
     matter for correctness and mean nothing at a form (Iran puts شهرستان between a province
     and a city). Those rows are real, and `in_path` keeps them out of the path a person
     reads and out of the pickers.

  2. A place is found by what people call it, not only by its name. `place.alias` holds the
     old name, the square, the metro stop, the landmark -- «کاخ» for فلسطین. Aliases are
     searched and never displayed: the answer still reads «فلسطین · منطقهٔ ۶ · تهران», so
     nobody is taught a name that is not the name.

  3. Ranking stays the published one. A place contributes its own names at full weight, its
     aliases below them, its ancestors lower and its neighbours lowest, so naming a
     neighbour finds the place -- through the same six match kinds search_suggest publishes,
     with no separate scoring rule hidden here.
"""
from math import cos, radians, sqrt

from odoo import api, fields, models
from odoo.exceptions import ValidationError

# How much a text about a place counts, compared with the place's own name (1.0).
# Written here, once, because a weight buried in a method is a weight nobody reads.
#
# A name the place once had, or that people use for it, is nearly its name. A landmark
# INSIDE it is weaker on purpose: a square or a metro stop stands in one place and is named
# for something else, so it should lose to any place actually called that.
ALIAS_WEIGHT = {'old': 0.9, 'colloquial': 0.9, 'spelling': 0.9,
                'square': 0.6, 'transit': 0.6, 'landmark': 0.6}
ALIAS_WEIGHT_DEFAULT = 0.6
PARENT_WEIGHT = 0.35      # «تهران» typed while looking for a neighbourhood of Tehran
NEIGHBOUR_WEIGHT = 0.25   # «ولیعصر» typed by someone who means the street beside it

KINDS = [
    ('country', "Country"),
    ('province', "Province"),
    ('county', "County"),
    ('city', "City"),
    ('village', "Village"),
    ('district', "District"),
    ('neighbourhood', "Neighbourhood"),
    ('street', "Street"),
    ('other', "Other"),
]
# How fine each kind is. Only the order matters: it says which kinds are above a place and
# which are below it, so a path can be built without asking how deep the tree happens to be
# in this country -- one has counties and districts, another neither.
FINENESS = {'country': 0, 'province': 1, 'county': 2, 'city': 3, 'village': 3,
            'district': 4, 'neighbourhood': 5, 'street': 6, 'other': 4}
# A path is read out the way an address is said: the place, the area of the city it is in,
# and the city (or, with no city above it, the province). The layers in between are true and
# unsaid -- nobody says «ناحیه ۲» to explain where a café is.
PATH_AREA_KINDS = ('neighbourhood', 'district')
PATH_PLACE_KINDS = ('city', 'village')
PATH_REGION_KINDS = ('province',)
# Equal scores keep the published order: the sequence a person set, then the id.
SUGGEST_ORDER = 'sequence, id'
PATH_SEPARATOR = ' · '
PATH_DEPTH = 3   # what a person reads: the place and the two shown places above it
MAX_DEPTH = 12   # how far up a tree is ever walked in one go: country to street is eight
KM_PER_DEGREE = 111.195   # a degree of latitude; longitude is scaled by cos(latitude)


class PlaceNode(models.Model):
    _name = 'place.node'
    _inherit = ['search.suggest.mixin']
    _description = "Place"
    _parent_store = True
    _order = 'sequence, name, id'
    _suggest_fields = {'name': 1.0, 'name_en': 0.8, 'code': 0.4}

    name = fields.Char("Name", required=True, translate=True, index='trigram')
    name_en = fields.Char("English name")
    code = fields.Char("Code", required=True, help="Stable, kebab-case, never re-pointed.")
    kind = fields.Selection(KINDS, string="Kind", required=True, default='city', index=True)
    sequence = fields.Integer("Sequence", default=100)
    active = fields.Boolean(default=True)

    parent_id = fields.Many2one('place.node', string="Part of", ondelete='restrict', index=True)
    parent_path = fields.Char(index=True, unaccent=False)
    child_ids = fields.One2many('place.node', 'parent_id', string="Parts")
    in_path = fields.Boolean(
        "Shown in the path", default=True,
        help="Off for a layer that is real but that nobody picks or reads, such as a county "
             "between a province and a city. It still holds its children and is still searched.")
    path = fields.Char("Path", compute='_compute_path', store=True, recursive=True,
                       help="How the place is read out: itself and the PATH_DEPTH - 1 shown "
                            "places above it, nearest first.")

    latitude = fields.Float("Latitude", digits=(9, 6))
    longitude = fields.Float("Longitude", digits=(9, 6))

    # Re-declared only to add `recursive`: a place is found by the names above it, so
    # renaming a city has to reach the index of everything inside it.
    suggest_index = fields.Text(
        "Search index", compute='_compute_suggest_index', store=True, readonly=True,
        recursive=True, copy=False)

    alias_ids = fields.One2many('place.alias', 'place_id', string="Also called")
    link_ids = fields.One2many('place.link', 'place_id', string="Neighbours")
    neighbour_ids = fields.Many2many('place.node', compute='_compute_neighbour_ids',
                                     string="Neighbouring places")
    postcode_ids = fields.One2many('place.postcode', 'place_id', string="Post code prefixes")
    source = fields.Char("Source", help="Where this row came from, for a reader who has to check it.")

    _code_uniq = models.Constraint('UNIQUE(code)', "A place code is used once.")

    # ------------------------------------------------------------------ computed
    @api.depends('name', 'in_path', 'kind', 'parent_id.path', 'parent_path')
    def _compute_path(self):
        """«فلسطین · دانشگاه تهران · تهران»: the place, the part of the city it is in, and the
        city. Not every layer it hangs off -- a path that says every true thing about a place
        is one nobody reads to the end, and the layers a register needs (a county, a ناحیه)
        are not how anybody says where they are."""
        for place in self:
            parts = [place.name] if place.in_path else []
            fineness = FINENESS.get(place.kind, 4)
            ancestors = [a for a in place.ancestor_places() if a.in_path]
            for kinds in (PATH_AREA_KINDS, PATH_PLACE_KINDS, PATH_REGION_KINDS):
                if len(parts) >= PATH_DEPTH:
                    break
                found = next((a for a in ancestors if a.kind in kinds
                              and FINENESS.get(a.kind, 4) < fineness), None)
                if found and found.name not in parts:
                    parts.append(found.name)
                    if kinds is PATH_PLACE_KINDS:
                        break          # a city says enough; its province is not needed too
            place.path = PATH_SEPARATOR.join(parts[:PATH_DEPTH])

    @api.depends('link_ids.other_id')
    def _compute_neighbour_ids(self):
        for place in self:
            place.neighbour_ids = place.link_ids.other_id

    @api.depends('name', 'path')
    def _compute_display_name(self):
        for place in self:
            place.display_name = place.path or place.name

    @api.constrains('parent_id')
    def _check_acyclic(self):
        if self._has_cycle():
            raise ValidationError("A place cannot be inside itself.")

    # -------------------------------------------------------------------- search
    @api.depends('alias_ids.name', 'alias_ids.kind', 'parent_id.suggest_index',
                 'link_ids.other_id.name')
    def _compute_suggest_index(self):
        return super()._compute_suggest_index()

    def _suggest_texts(self):
        """The place's own names, then what else leads a person to it, each with its weight."""
        texts = super()._suggest_texts()
        for alias in self.alias_ids:
            texts.append(('alias', ALIAS_WEIGHT.get(alias.kind, ALIAS_WEIGHT_DEFAULT), alias.name))
        for ancestor in self.ancestor_places():
            texts.append(('parent', PARENT_WEIGHT, ancestor.name))
        for neighbour in self.link_ids.other_id:
            texts.append(('neighbour', NEIGHBOUR_WEIGHT, neighbour.name))
        return texts

    @api.model
    def _suggest_rank(self, query, records, limit, boost=None):
        """Read in batches what the ranking would otherwise ask for one row at a time.

        Ranking a place reads its aliases, the names above it and its neighbours. Asked per
        row over a thousand candidates that is thousands of queries; asked once per level it
        is a dozen. Nothing about the scores changes -- only when the values are read."""
        records.fetch(['name', 'name_en', 'code', 'kind', 'in_path', 'parent_id'])
        records.alias_ids.fetch(['name', 'kind'])
        records.link_ids.other_id.fetch(['name'])
        level = records.parent_id
        for _depth in range(MAX_DEPTH):
            if not level:
                break
            level.fetch(['name', 'parent_id'])
            level = level.parent_id
        return super()._suggest_rank(query, records, limit, boost)

    def place_of_kinds(self, kinds):
        """This place if it is one of `kinds`, else the nearest place above it that is.

        How a record shows a coarser place than the one it holds, and how a city or a province
        is read off a neighbourhood: one walk up the tree, no rule repeated anywhere else."""
        if not self:
            return self
        self.ensure_one()
        for place in self + self.ancestor_places():
            if place.kind in kinds:
                return place
        return self.browse()

    def distance_km(self, other):
        """Roughly how far apart two places are, by their points. False if either has none.

        Great-circle on a sphere: this answers «is that across the city or across the country»,
        which is all a person needs from it, and all the points in the tree support."""
        self.ensure_one()
        if not other or not (self.latitude or self.longitude) or not (other.latitude or other.longitude):
            return False
        mean_latitude = radians((self.latitude + other.latitude) / 2.0)
        north = (self.latitude - other.latitude) * KM_PER_DEGREE
        east = (self.longitude - other.longitude) * KM_PER_DEGREE * cos(mean_latitude)
        return sqrt(north * north + east * east)

    def ancestor_places(self):
        """The places above this one, nearest first, shown or not."""
        self.ensure_one()
        chain, parent = self.browse(), self.parent_id
        while parent and parent not in chain:
            chain |= parent
            parent = parent.parent_id
        return chain

    @api.model
    def suggest_places(self, query, kinds=None, within=None, limit=10, domain=None, widen=True):
        """Suggestions for `query`, best first, with the place a person is already inside
        counting for more. `within` is a place (or its id): its own places are ranked above
        same-named places elsewhere, which is what someone typing «فلسطین» in Tehran means.
        `domain` narrows what may be answered at all -- one country, one city, one kind.
        `widen=False` is the quick answer a page shows while the full one is still coming."""
        domain = list(domain or []) + ([('kind', 'in', list(kinds))] if kinds else [])
        boost = None
        if within:
            within_id = within if isinstance(within, int) else within.id
            boost = [([('id', 'child_of', within_id)], 1.0 + PARENT_WEIGHT)]
        return self.suggest(query, domain=domain, limit=limit, order=SUGGEST_ORDER, boost=boost,
                            widen=widen)
