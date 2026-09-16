# Part of iKiKu. Licensed under AGPL-3.0.
"""Cost recovery, shared -- not a commission on placements.

The co-op does not take a cut of anyone's wage. It adds up what it actually cost
to run the platform for a period, and divides that across the businesses that
used it, in proportion to the person-days they booked.

Person-days is the driver because it is the one measure both sides can check
against the public booking record: a booking's dates are already published, so
the basis of every invoice is auditable by the person being invoiced.

The claim "as the system grows, the cost falls" is arithmetic, not marketing --
the same fixed cost over more person-days is a smaller rate. `rate_change_pct`
computes it against the previous period so the claim can be checked rather than
believed.
"""
from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.ikiku_base.models.jalali import format_jalali


class IkikuCostPeriod(models.Model):
    _name = 'ikiku.cost.period'
    _description = "دورهٔ هزینه"
    _inherit = ['mail.thread']
    _order = 'date_start desc'

    name = fields.Char("نام دوره", required=True)
    date_start = fields.Date("از تاریخ", required=True)
    date_end = fields.Date("تا تاریخ", required=True)
    currency_id = fields.Many2one('res.currency', string="واحد پول", required=True,
                                  default=lambda s: s.env.company.currency_id)
    total_cost = fields.Monetary("هزینهٔ کلِ دوره", currency_field='currency_id',
                                 required=True, tracking=True,
                                 help="هزینهٔ واقعیِ اداره‌کردنِ پلتفرم. نه بیشتر.")
    cost_note = fields.Text("ریزِ هزینه",
                            help="بند ۸: هزینه‌ای که تقسیم می‌شود باید قابلِ خواندن باشد.")
    share_ids = fields.One2many('ikiku.cost.share', 'period_id', string="سهم‌ها")

    total_person_days = fields.Integer("جمعِ روز-نفر", compute='_compute_totals', store=True)
    business_count = fields.Integer("تعداد کسب‌وکار", compute='_compute_totals', store=True)
    rate_per_person_day = fields.Monetary("نرخِ هر روز-نفر", currency_field='currency_id',
                                          compute='_compute_totals', store=True)
    previous_period_id = fields.Many2one('ikiku.cost.period', string="دورهٔ پیشین",
                                         compute='_compute_previous', store=True)
    rate_change_pct = fields.Float("تغییرِ نرخ نسبت به دورهٔ پیشین (٪)",
                                   compute='_compute_previous', store=True)

    state = fields.Selection([
        ('draft', "پیش‌نویس"),
        ('allocated', "تقسیم‌شده"),
        ('closed', "بسته"),
    ], default='draft', required=True, tracking=True, string="وضعیت")
    is_public = fields.Boolean("انتشارِ عمومی", default=True,
                               help="بند ۸: نه رتبه با فرمولِ پنهان، نه هزینه با رقمِ پنهان.")

    date_start_fa = fields.Char(compute='_compute_fa', string="از (شمسی)")
    date_end_fa = fields.Char(compute='_compute_fa', string="تا (شمسی)")

    @api.depends('date_start', 'date_end')
    def _compute_fa(self):
        for rec in self:
            rec.date_start_fa = format_jalali(rec.date_start)
            rec.date_end_fa = format_jalali(rec.date_end)

    @api.depends('share_ids.person_days', 'total_cost')
    def _compute_totals(self):
        for rec in self:
            rec.total_person_days = sum(rec.share_ids.mapped('person_days'))
            rec.business_count = len(rec.share_ids.mapped('business_id'))
            rec.rate_per_person_day = (
                rec.total_cost / rec.total_person_days if rec.total_person_days else 0.0)

    @api.depends('date_start', 'rate_per_person_day')
    def _compute_previous(self):
        for rec in self:
            previous = self.search([('date_end', '<', rec.date_start),
                                    ('state', '!=', 'draft')],
                                   order='date_end desc', limit=1)
            rec.previous_period_id = previous
            if previous and previous.rate_per_person_day:
                rec.rate_change_pct = 100.0 * (
                    rec.rate_per_person_day - previous.rate_per_person_day
                ) / previous.rate_per_person_day
            else:
                rec.rate_change_pct = 0.0

    def _person_days(self, booking):
        """Days of this booking that fall inside this period. A booking with no end
        date runs to the end of every period it reaches."""
        self.ensure_one()
        start = max(booking.date_start, self.date_start)
        end = min(booking.date_end or self.date_end, self.date_end)
        return (end - start).days + 1 if end >= start else 0

    def action_allocate(self):
        """Divide the period's real cost across the businesses that used it."""
        self.ensure_one()
        if self.state == 'closed':
            raise UserError("دورهٔ بسته دوباره تقسیم نمی‌شود.")
        if not self.total_cost:
            raise UserError("پیش از تقسیم، هزینهٔ کلِ دوره را وارد کنید.")
        self.share_ids.unlink()
        bookings = self.env['ikiku.booking'].search([
            ('state', 'in', ('confirmed', 'in_progress', 'done')),
            ('date_start', '<=', self.date_end),
            '|', ('date_end', '=', False), ('date_end', '>=', self.date_start),
        ])
        per_business = {}
        for booking in bookings:
            days = self._person_days(booking)
            if days:
                per_business.setdefault(booking.employer_business_id, 0)
                per_business[booking.employer_business_id] += days
        total_days = sum(per_business.values())
        if not total_days:
            raise UserError("در این دوره هیچ گمارشی نبوده؛ چیزی برای تقسیم نیست.")
        rate = self.total_cost / total_days
        Share = self.env['ikiku.cost.share']
        for business, days in per_business.items():
            Share.create({
                'period_id': self.id, 'business_id': business.id,
                'person_days': days, 'amount': rate * days,
            })
        self.state = 'allocated'
        self.message_post(
            body="تقسیم شد: %d روز-نفر میانِ %d کسب‌وکار."
                 % (total_days, len(per_business)))


class IkikuCostShare(models.Model):
    _name = 'ikiku.cost.share'
    _description = "سهمِ کسب‌وکار از هزینه"
    _order = 'amount desc'

    period_id = fields.Many2one('ikiku.cost.period', required=True, ondelete='cascade',
                                index=True, string="دوره")
    business_id = fields.Many2one('ikiku.business', required=True, ondelete='restrict',
                                  index=True, string="کسب‌وکار")
    currency_id = fields.Many2one(related='period_id.currency_id')
    person_days = fields.Integer("روز-نفر", required=True)
    amount = fields.Monetary("سهم", currency_field='currency_id', required=True)
    share_pct = fields.Float("درصد", compute='_compute_pct', store=True)
    paid = fields.Boolean("پرداخت شد", default=False)

    _period_business_uniq = models.Constraint(
        'UNIQUE(period_id, business_id)', "برای هر دوره، هر کسب‌وکار یک سهم.")

    @api.depends('person_days', 'period_id.total_person_days')
    def _compute_pct(self):
        for rec in self:
            total = rec.period_id.total_person_days
            rec.share_pct = 100.0 * rec.person_days / total if total else 0.0
