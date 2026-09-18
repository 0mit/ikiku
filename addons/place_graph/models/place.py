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
import json
from math import cos, radians, sqrt

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.place_graph.tools import tree
# The rules live in tools/tree.py, once, because the bundle loader, the pipeline and the
# responder need exactly the same ones; these names are kept so nothing that imported them
# from here has to change.
from odoo.addons.place_graph.tools.tree import (  # noqa: F401
    ALIAS_WEIGHT, ALIAS_WEIGHT_DEFAULT, FINENESS, KINDS, MAX_DEPTH, NEIGHBOUR_WEIGHT,
    PARENT_WEIGHT, PATH_AREA_KINDS, PATH_DEPTH, PATH_PLACE_KINDS, PATH_REGION_KINDS,
    PATH_SEPARATOR, PICKER_KINDS, SUGGEST_ORDER)

KM_PER_DEGREE = 111.195   # a degree of latitude; longitude is scaled by cos(latitude)
# Where a row came from, so a loader knows what it may change. A bundle row is the source's
# until a person changes it; what a person decided -- a place staff added, an alias somebody
# suggested and staff ratified -- is the overlay, and no bundle ever overwrites or retires it.
ORIGINS = [('bundle', "Imported (bundle)"), ('overlay', "Decided here")]
# The fields a bundle carries. When a person edits one of them on a bundle row, the field is
# written into `kept_fields`, and the next bundle load leaves that field alone.
BUNDLE_FIELDS = ('name', 'name_en', 'kind', 'parent_id', 'in_path', 'latitude', 'longitude',
                 'active')
LOADING = 'place_bundle_loading'   # context key the loader sets: its writes are the source's
SPEC_PARAM = 'place_graph.responder_spec'
NOTIFY_CHANNEL = 'place_graph_changed'


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
    origin = fields.Selection(ORIGINS, string="Origin", required=True, default='overlay', index=True,
                              help="Imported rows follow their bundle; rows decided here are never "
                                   "changed or retired by a bundle.")
    kept_fields = fields.Char(
        "Kept by a person", readonly=True, copy=False,
        help="Fields of an imported row that a person changed. A bundle load leaves them alone.")

    _code_uniq = models.Constraint('UNIQUE(code)', "A place code is used once.")

    # ------------------------------------------------------------------ computed
    @api.depends('name', 'in_path', 'kind', 'parent_id.path', 'parent_path')
    def _compute_path(self):
        """«فلسطین · دانشگاه تهران · تهران»: the place, the part of the city it is in, and the
        city -- tree.read_path, which the bundle loader uses too."""
        for place in self:
            place.path = tree.read_path(
                (place.name, place.kind, place.in_path),
                [(a.name, a.kind, a.in_path) for a in place.ancestor_places()])

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
    @api.depends('alias_ids.name', 'alias_ids.kind', 'alias_ids.active', 'parent_id.suggest_index',
                 'link_ids.other_id.name', 'link_ids.active')
    def _compute_suggest_index(self):
        return super()._compute_suggest_index()

    def _suggest_texts(self):
        """The place's own names, then what else leads a person to it, each with its weight
        (tree.suggest_texts, the same list the bundle loader and the responder build)."""
        own = super()._suggest_texts()
        names = [value for field, _weight, value in own if field == 'name']
        return tree.suggest_texts(
            names, self.name_en, self.code,
            [(alias.name, alias.kind) for alias in self.alias_ids],
            [ancestor.name for ancestor in self.ancestor_places()],
            [neighbour.name for neighbour in self.link_ids.other_id])

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
        # Kinds are NOT a filter of what may match, only of what may be answered: a finer place
        # that matches answers as the nearest offered place above it (tree.climb), and says
        # which place it came through. So «کرشته», a neighbourhood, answers شهریار on a form
        # that asks for a city.
        allowed = set(kinds) if kinds else None
        boost = None
        if within:
            within_id = within if isinstance(within, int) else within.id
            boost = [([('id', 'child_of', within_id)], 1.0 + PARENT_WEIGHT)]
        found = self.suggest(query, domain=list(domain or []), limit=max(limit * 4, 40) if allowed else limit,
                             order=SUGGEST_ORDER, boost=boost, widen=widen)
        answers = {}
        for result in found:
            place = result['record']
            above = place.ancestor_places()
            step = tree.climb(place.kind, [(a.kind, a.active) for a in above], allowed)
            if step is None:
                continue
            target = place if step == 'self' else above[step]
            answer = dict(result, record=target)
            if step != 'self':
                answer['via'] = place
            have = answers.get(target.id)
            if not have or answer['score'] > have['score'] or (
                    answer['score'] == have['score'] and 'via' in have and 'via' not in answer):
                answers[target.id] = answer
        # Equal scores: a place called this before one that only contains something called this
        # («محلات» the city before the cities with a street of that name), then the order.
        ordered = sorted(answers.values(), key=lambda r: (-r['score'], 'via' in r, r['record'].sequence,
                                                          r['record']._city_sequence(), r['record'].id))
        return ordered[:limit]

    def _city_sequence(self):
        self.ensure_one()
        return tree.city_sequence(self.kind, self.sequence,
                                  [(a.kind, a.sequence) for a in self.ancestor_places()])

    # ------------------------------------------------------------------ overlay
    def write(self, vals):
        """A person changing an imported row takes that field over from the bundle.

        The loader writes with LOADING in its context (and mostly in SQL); anything else that
        touches a field the bundle carries is somebody's decision, and the next load must
        leave it where they put it."""
        if not self.env.context.get(LOADING):
            touched = [name for name in BUNDLE_FIELDS if name in vals]
            if touched:
                for place in self.filtered(lambda p: p.origin == 'bundle'):
                    kept = set(filter(None, (place.kept_fields or '').split(',')))
                    if not kept.issuperset(touched):
                        super(PlaceNode, place).write(
                            {'kept_fields': ','.join(sorted(kept.union(touched)))})
        return super().write(vals)

    # ---------------------------------------------------------------- responder
    def init(self):
        """What a responder outside Odoo needs from this database, kept current on every
        install and update: the ranking spec, and a notification whenever places change.

        The spec is tree.spec() -- the weights, match kinds and picker kinds this module ranks
        with -- so a responder never carries a number of its own. The triggers send
        NOTIFY place_graph_changed on every statement that changes a place table; Postgres
        delivers it at COMMIT and not before, so a responder reloads only what was really
        written, and a rolled-back import tells it nothing."""
        super().init()
        cr = self.env.cr
        spec = json.dumps(tree.spec(), sort_keys=True, ensure_ascii=False)
        cr.execute("""
            INSERT INTO ir_config_parameter (key, value, create_uid, write_uid, create_date, write_date)
            VALUES (%s, %s, 1, 1, now() at time zone 'UTC', now() at time zone 'UTC')
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, write_date = EXCLUDED.write_date
            WHERE ir_config_parameter.value IS DISTINCT FROM EXCLUDED.value
        """, (SPEC_PARAM, spec))
        # The responder reads the spec through this view and nothing else of the parameters:
        # ir_config_parameter also holds secrets (API keys, the database secret), and a role
        # that may read the places must not be able to read those. See
        # services/place_responder/deploy/places_ro.sql.
        # Created once: replacing a view takes an exclusive lock on it, which a reading
        # responder can hold up past the lock timeout of a live update.
        cr.execute("SELECT to_regclass('place_responder_spec')")
        if not cr.fetchone()[0]:
            cr.execute("""CREATE VIEW place_responder_spec AS
                          SELECT value FROM ir_config_parameter WHERE key = %s""", (SPEC_PARAM,))
        self._place_notify_on(self._table)
        cr.execute("SELECT pg_notify(%s, 'spec')", (NOTIFY_CHANNEL,))

    @api.model
    def _place_notify_on(self, table):
        """NOTIFY place_graph_changed after every statement that changes `table`. Each place
        table asks for this from its own init(), which runs once its table exists."""
        self.env.cr.execute("""
            CREATE OR REPLACE FUNCTION place_graph_notify() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                PERFORM pg_notify('%s', TG_TABLE_NAME);
                RETURN NULL;
            END $$
        """ % NOTIFY_CHANNEL)
        # Only when missing: CREATE TRIGGER takes an exclusive lock on the table, and on a live
        # site the lock may not come in time (it did not, on 2026-09-18, with the site serving
        # and the responder reading). Once the trigger is there, an update touches nothing.
        self.env.cr.execute("""SELECT 1 FROM pg_trigger WHERE tgname = 'place_graph_notify'
                               AND tgrelid = %s::regclass""", (table,))
        if not self.env.cr.fetchone():
            self.env.cr.execute("""
                CREATE TRIGGER place_graph_notify
                    AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE ON {0}
                    FOR EACH STATEMENT EXECUTE FUNCTION place_graph_notify();
            """.format(table))
