# Part of iKiKu. Licensed under AGPL-3.0.
"""Ranking that a person can read.

The مرام‌نامه forbids a score whose derivation is hidden:
"رتبه را با فرمولِ پنهان نمی‌سازیم؛ هر عددی که نشان می‌دهیم، راهِ رسیدن به آن هم پیداست."

That rules out a learned ranker -- not only for the MVP but for as long as that
sentence stands. So the weights are constants declared here, every component is
STORED on the proposal, and the explanation is generated from the same numbers
the total is generated from. There is no second code path that could disagree.
"""
from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.ikiku_base.models.jalali import format_jalali, to_fa_digits

# The published weights. Changing one is a visible change to a public rule.
W_COMPETENCY = 3.0
W_HISTORY = 2.0
W_STANDING = 1.5
W_PROXIMITY = 1.0
W_SEASON = 0.5

# The MVP horizon: a business plans a quarter out, and we look three months
# beyond that. Both ends are configurable, neither is hard-coded into a query.
HORIZON_FROM_DAYS = 90
HORIZON_TO_DAYS = 180


class IkikuProposal(models.Model):
    _name = 'ikiku.proposal'
    _description = "پیشنهادِ نیرو"
    _order = 'score_total desc'

    demand_id = fields.Many2one('ikiku.demand', required=True, ondelete='cascade',
                                index=True, string="نیاز")
    resource_id = fields.Many2one('ikiku.resource', required=True, ondelete='cascade',
                                  index=True, string="نیرو")
    availability_id = fields.Many2one('ikiku.availability', string="بازهٔ در دسترس")

    score_competency = fields.Float("مهارت", readonly=True)
    score_history = fields.Float("سابقهٔ راست‌آزمایی‌شده", readonly=True)
    score_standing = fields.Float("اعتبار", readonly=True)
    score_proximity = fields.Float("نزدیکی", readonly=True)
    score_season = fields.Float("فصل", readonly=True)
    score_total = fields.Float("جمع", readonly=True, index=True)
    explanation = fields.Text("چگونه به این عدد رسیدیم", readonly=True)

    state = fields.Selection([
        ('proposed', "پیشنهاد شده"),
        ('accepted', "پذیرفته"),
        ('declined', "رد شده"),
        ('expired', "منقضی"),
    ], default='proposed', required=True, string="وضعیت")
    decline_reason = fields.Char("دلیلِ رد")

    _demand_resource_uniq = models.Constraint(
        'UNIQUE(demand_id, resource_id)', "برای هر نیاز، هر نیرو یک بار پیشنهاد می‌شود.")

    # ---------------------------------------------------------------- scoring
    @api.model
    def _score(self, demand, resource, availability):
        position = demand.position_id
        required = position.required_node_ids
        nice = position.nice_node_ids
        held = resource.skill_ids.mapped('skill_id.name')
        # A resource "has" a node if a supported assertion names it.
        supported_nodes = resource.assertion_ids.filtered(
            lambda a: a.state == 'supported').mapped('spec_node_id')

        req_hit = len(required & supported_nodes) / len(required) if required else 1.0
        nice_hit = len(nice & supported_nodes) / len(nice) if nice else 0.0
        competency = W_COMPETENCY * (0.8 * req_hit + 0.2 * nice_hit)

        experience = resource.assertion_ids.filtered(
            lambda a: a.claim_kind == 'experience' and a.state == 'supported')
        history = W_HISTORY * min(len(experience) / 3.0, 1.0)

        standing = W_STANDING * (resource.standing / 5.0)

        if availability and availability.province_id == demand.province_id:
            proximity_raw = 1.0
        elif availability and availability.can_relocate:
            proximity_raw = 0.5
        else:
            proximity_raw = 0.0
        proximity = W_PROXIMITY * proximity_raw

        season = W_SEASON * min(demand.season_factor or 1.0, 2.0) / 2.0

        total = competency + history + standing + proximity + season
        lines = [
            "مهارت: %s از %s — %d مهارتِ الزامی از %d پشتیبانی شده."
            % (to_fa_digits(round(competency, 2)), to_fa_digits(W_COMPETENCY),
               len(required & supported_nodes), len(required)),
            "سابقه: %s از %s — %d سابقهٔ راست‌آزمایی‌شده."
            % (to_fa_digits(round(history, 2)), to_fa_digits(W_HISTORY), len(experience)),
            "اعتبار: %s از %s — اعتبارِ کنونی %s از ۵."
            % (to_fa_digits(round(standing, 2)), to_fa_digits(W_STANDING),
               to_fa_digits(round(resource.standing, 2))),
            "نزدیکی: %s از %s — %s."
            % (to_fa_digits(round(proximity, 2)), to_fa_digits(W_PROXIMITY),
               "همان استان" if proximity_raw == 1.0
               else ("امکانِ جابه‌جایی دارد" if proximity_raw else "استانِ دیگر")),
            "فصل: %s از %s — ضریبِ تقاضا %s."
            % (to_fa_digits(round(season, 2)), to_fa_digits(W_SEASON),
               to_fa_digits(round(demand.season_factor or 1.0, 2))),
            "نوعِ همکاری: %s — %s."
            % (demand.work_type_id.name or "گفته نشده",
               "می‌پذیرد" if availability and demand.work_type_id in availability.work_type_ids
               else "نوعِ همکاری را نگفته، پس کنار گذاشته نشد"),
            "زمان: آزاد از %s تا %s%s."
            % (availability.date_start_fa if availability else "—",
               availability.date_end_fa if availability else "—",
               "؛ این نیاز پایان ندارد" if not demand.date_end else ""),
            "جمع: %s" % to_fa_digits(round(total, 2)),
        ]
        return {
            'score_competency': competency, 'score_history': history,
            'score_standing': standing, 'score_proximity': proximity,
            'score_season': season, 'score_total': total,
            'explanation': "\n".join(lines),
        }

    @api.model
    def build_for_demand(self, demand, limit=20):
        """Find resources free for the need and rank them.

        A need with an end date needs someone free for the whole window. A need with
        no end date (operator, 2026-09-16) goes to anyone free from its start; the
        explanation then says how long they are free. Either way the kind of work must
        be one the worker accepts, or one they have not ruled out by naming none.
        None of this changes a weight: it decides who is ranked, not how."""
        if demand.state not in ('open', 'proposed'):
            raise UserError("فقط برای نیازِ باز می‌توان پیشنهاد ساخت.")
        Availability = self.env['ikiku.availability']
        until = demand.date_end or demand.date_start
        candidates = Availability.search([
            ('state', '=', 'open'),
            ('date_start', '<=', demand.date_start),
            '|', ('date_end', '=', False), ('date_end', '>=', until),
            '|', ('work_type_ids', '=', False), ('work_type_ids', 'in', demand.work_type_id.ids),
            ('resource_id.state', '=', 'active'),
            '|', ('province_id', '=', demand.province_id.id), ('can_relocate', '=', True),
        ])
        made = self.browse()
        for availability in candidates:
            resource = availability.resource_id
            if self.search_count([('demand_id', '=', demand.id),
                                  ('resource_id', '=', resource.id)]):
                continue
            vals = self._score(demand, resource, availability)
            vals.update({'demand_id': demand.id, 'resource_id': resource.id,
                         'availability_id': availability.id})
            made |= self.create(vals)
        if made:
            demand.state = 'proposed'
        return made.sorted(lambda p: -p.score_total)[:limit]

    def action_accept(self):
        """Accepting creates the booking, which is published immediately."""
        self.ensure_one()
        booking = self.env['ikiku.booking'].create({
            'demand_id': self.demand_id.id,
            'resource_id': self.resource_id.id,
            'availability_id': self.availability_id.id,
            'proposal_id': self.id,
        })
        self.state = 'accepted'
        return booking
