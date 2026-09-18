# Part of place_graph. Licensed under AGPL-3.0.
"""What people say the map is missing, and what a person here decided about it.

The map is the source's; the people who use it know things the source does not. «علیشاه عوض»
is what the old folk of شهریار still call it; a new شهرک has no row yet; a street changed its
name. Those are SUGGESTIONS, and a suggestion changes nothing by itself. A place editor
ratifies it -- and only then is it written, into the OVERLAY: rows with origin 'overlay',
which no bundle load ever changes or retires, or fields of an imported row that the editor
took over (`kept_fields`). Or the editor rejects it, and says why, because the person who
asked deserves the reason and the next editor deserves to not decide it again.

Where suggestions come from:
  portal  somebody typed a place the search did not know and then chose another -- the text
          they typed is suggested as another name for what they chose (never automatically
          added: a street address is not a place's name, and a person decides that);
  staff   an editor wrote it;
  import  a source that is not trusted enough to load unseen (a harvest of former names, a
          gazetteer of villages) offers rows for a person to confirm.

The same suggestion made again is not a second row: `times` counts it, so an editor sees
that forty people call شهریار «علیشاه عوض», not forty rows.
"""
from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from odoo.addons.search_suggest.tools import text as text_of
from odoo.addons.place_graph.tools.tree import ALIAS_KINDS, KINDS

ACTIONS = [
    ('alias', "Another name for a place"),
    ('place', "A place that is missing"),
    ('rename', "Its name is different"),
    ('move', "It is inside another place"),
    ('retire', "It does not exist"),
    ('postcode', "A post code prefix belongs to it"),
]
STATES = [('proposed', "Waiting"), ('ratified', "Ratified"), ('rejected', "Rejected")]
ORIGINS = [('portal', "Somebody on the site"), ('staff', "Staff"), ('import', "A source, to be confirmed")]
PREFIX_LENGTH = 5


class PlaceSuggestion(models.Model):
    _name = 'place.suggestion'
    _description = "A suggested change to the places"
    _order = 'state, times desc, id desc'

    name = fields.Char("What was suggested", required=True,
                       help="The name, as it was written. For a post code, its first five digits only.")
    action = fields.Selection(ACTIONS, string="Suggestion", required=True, default='alias')
    place_id = fields.Many2one('place.node', string="Place", index=True, ondelete='cascade',
                               help="The place it is about -- for a missing place, the place it is inside.")
    alias_kind = fields.Selection(ALIAS_KINDS, string="Kind of name", default='colloquial')
    place_kind = fields.Selection(KINDS, string="Kind of place", default='neighbourhood')
    new_parent_id = fields.Many2one('place.node', string="Inside", ondelete='set null')
    latitude = fields.Float("Latitude", digits=(9, 6))
    longitude = fields.Float("Longitude", digits=(9, 6))
    note = fields.Text("Why", help="What the person who suggested it said, or where it comes from.")
    origin = fields.Selection(ORIGINS, string="From", required=True, default='staff')
    user_id = fields.Many2one('res.users', string="Suggested by", default=lambda self: self.env.user,
                              ondelete='set null')
    times = fields.Integer("Times suggested", default=1, readonly=True)
    folded = fields.Char("Folded", compute='_compute_folded', store=True, index=True,
                         help="The name folded for comparison: the same suggestion made again is counted, "
                              "not written twice.")

    state = fields.Selection(STATES, string="State", required=True, default='proposed', index=True,
                             readonly=True)
    decided_by = fields.Many2one('res.users', string="Decided by", readonly=True, ondelete='set null')
    decided_on = fields.Datetime("Decided on", readonly=True)
    decision_note = fields.Text("Decision", help="Required when rejecting: why not.")
    result_place_id = fields.Many2one('place.node', string="Place written", readonly=True, ondelete='set null')

    @api.depends('name')
    def _compute_folded(self):
        for suggestion in self:
            suggestion.folded = text_of.spaced(suggestion.name or '')

    @api.constrains('action', 'name', 'place_id', 'new_parent_id')
    def _check_complete(self):
        for suggestion in self:
            if suggestion.action != 'place' and not suggestion.place_id:
                raise ValidationError("Say which place the suggestion is about.")
            if suggestion.action == 'move' and not suggestion.new_parent_id:
                raise ValidationError("Say which place it is inside.")
            if suggestion.action == 'postcode':
                prefix = suggestion.name or ''
                if not (prefix.isdigit() and prefix.isascii() and len(prefix) == PREFIX_LENGTH):
                    raise ValidationError("A post code suggestion keeps the first %d digits and nothing "
                                          "more." % PREFIX_LENGTH)

    # ---------------------------------------------------------------- suggesting
    @api.model
    def suggest(self, values):
        """Record a suggestion, or count it again if the same one is already waiting.
        Returns the suggestion. The door the portal uses, with sudo."""
        name = ' '.join((values.get('name') or '').split())
        if not name:
            return self.browse()
        values = dict(values, name=name)
        same = self.search([
            ('state', '=', 'proposed'), ('action', '=', values.get('action', 'alias')),
            ('place_id', '=', values.get('place_id') or False),
            ('folded', '=', text_of.spaced(name)),
        ], limit=1)
        if same:
            same.times += 1
            return same
        return self.create(values)

    # ------------------------------------------------------------------ deciding
    def _check_editor(self):
        if not (self.env.su or self.env.user.has_group('place_graph.group_place_editor')):
            raise UserError("Only a place editor decides a suggestion.")

    def action_ratify(self):
        """Write what was suggested into the overlay, and say who decided it."""
        self._check_editor()
        for suggestion in self:
            if suggestion.state != 'proposed':
                raise UserError("«%s» was already decided." % suggestion.name)
            written = suggestion._apply()
            suggestion.write({'state': 'ratified', 'decided_by': self.env.user.id,
                              'decided_on': fields.Datetime.now(),
                              'result_place_id': written.id if written else False})
        return True

    def action_reject(self):
        self._check_editor()
        for suggestion in self:
            if suggestion.state != 'proposed':
                raise UserError("«%s» was already decided." % suggestion.name)
            if not (suggestion.decision_note or '').strip():
                raise UserError("Write why «%s» is rejected: the person who suggested it, and the next "
                                "editor, need the reason." % suggestion.name)
            suggestion.write({'state': 'rejected', 'decided_by': self.env.user.id,
                              'decided_on': fields.Datetime.now()})
        return True

    def action_reopen(self):
        """A decision made by mistake goes back to waiting. What a ratification wrote stays:
        undoing it is an edit of its own, made on the place."""
        self._check_editor()
        self.write({'state': 'proposed', 'decided_by': False, 'decided_on': False})
        return True

    def _apply(self):
        """The change itself. Everything it writes is the overlay: origin 'overlay' on a new
        row, or a field the editor took over on an imported one (place.write keeps it)."""
        self.ensure_one()
        Place = self.env['place.node'].sudo()
        source = 'suggestion:%d' % self.id
        if self.action == 'alias':
            alias = self.env['place.alias'].sudo().with_context(active_test=False).search(
                [('place_id', '=', self.place_id.id), ('name', '=', self.name)], limit=1)
            if alias:
                alias.write({'active': True, 'kind': self.alias_kind})
            else:
                self.env['place.alias'].sudo().create({
                    'place_id': self.place_id.id, 'name': self.name, 'kind': self.alias_kind or 'colloquial',
                    'origin': 'overlay', 'source': source})
            return self.place_id
        if self.action == 'place':
            values = {'name': self.name, 'kind': self.place_kind or 'neighbourhood',
                      'parent_id': self.place_id.id or False, 'code': 'local-%d' % self.id,
                      'origin': 'overlay', 'source': source,
                      'sequence': Place._bundle_sequence(self.place_kind, self.name)}
            if self.latitude or self.longitude:
                values.update(latitude=self.latitude, longitude=self.longitude)
            return Place.create(values)
        if self.action == 'rename':
            self.place_id.sudo().write({'name': self.name})
            return self.place_id
        if self.action == 'move':
            self.place_id.sudo().write({'parent_id': self.new_parent_id.id})
            return self.place_id
        if self.action == 'retire':
            self.place_id.sudo().write({'active': False})
            return self.place_id
        if self.action == 'postcode':
            Postcode = self.env['place.postcode'].sudo()
            row = Postcode.search([('prefix', '=', self.name), ('place_id', '=', self.place_id.id)], limit=1)
            if row:
                row.write({'source': 'staff'})
            else:
                Postcode.create({'prefix': self.name, 'place_id': self.place_id.id, 'source': 'staff'})
            return self.place_id
        raise UserError("Nothing to do for a suggestion of kind %s." % self.action)
