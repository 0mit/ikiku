# Part of iKiKu. Licensed under AGPL-3.0.
"""The booking: publicly acknowledged, and deliberately incomplete in public.

بند ۷, ratified: the RECORD is public, the CALENDAR is not. On confirmation the
platform publishes that this person is committed, for these dates, in this
province -- and withholds the venue and the hours until the shift begins, unless
both sides opt in. The accountability survives; the map does not.

Cancellation is public the moment it happens. That is where the enforcement
actually lives: a commitment cannot be quietly withdrawn by either side.

iKiKu is not the employer. `employer_business_id` names who is.
"""
from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from odoo.addons.ikiku_base.models.jalali import format_jalali

CHECKPOINTS = [('t14', "۱۴ روز مانده"), ('t3', "۳ روز مانده"), ('t24', "۲۴ ساعت مانده")]
CHECKPOINT_DAYS = {'t14': 14, 't3': 3, 't24': 1}


class IkikuBooking(models.Model):
    _name = 'ikiku.booking'
    _description = "گمارش"
    _inherit = ['mail.thread']
    _order = 'date_start desc'

    name = fields.Char(compute='_compute_name', store=True)
    public_ref = fields.Char("شناسهٔ عمومی", copy=False, index=True, readonly=True)
    demand_id = fields.Many2one('ikiku.demand', required=True, ondelete='restrict',
                                index=True, string="نیاز")
    proposal_id = fields.Many2one('ikiku.proposal', string="پیشنهاد", readonly=True)
    resource_id = fields.Many2one('ikiku.resource', required=True, ondelete='restrict',
                                  index=True, string="نیرو", tracking=True)
    availability_id = fields.Many2one('ikiku.availability', string="بازه")
    employer_business_id = fields.Many2one(
        related='demand_id.business_id', store=True, string="کارفرما",
        help="کارفرما همین کسب‌وکار است. ایکیکو کارفرما نیست؛ ثبت می‌کند و صنف است.")
    date_start = fields.Date(related='demand_id.date_start', store=True, string="از تاریخ")
    date_end = fields.Date(related='demand_id.date_end', store=True, string="تا تاریخ")
    province_id = fields.Many2one(related='demand_id.province_id', store=True, string="استان")

    venue_public = fields.Boolean(
        "نمایشِ عمومیِ محلِ کار", default=False,
        help="بند ۷: تا شروعِ کار، محل و ساعت عمومی نیست مگر هر دو طرف بخواهند.")
    venue_disclosed = fields.Boolean(compute='_compute_venue_disclosed', store=True)

    state = fields.Selection([
        ('confirmed', "تأییدشده"),
        ('at_risk', "در معرضِ خطر"),
        ('replaced', "جایگزین شد"),
        ('in_progress', "در جریان"),
        ('done', "پایان‌یافته"),
        ('cancelled', "لغو شد"),
    ], default='confirmed', required=True, tracking=True, string="وضعیت")
    cancel_reason = fields.Text("دلیلِ لغو", tracking=True)
    cancelled_by_id = fields.Many2one('res.partner', string="لغوکننده", readonly=True)
    replaced_by_id = fields.Many2one('ikiku.booking', string="گمارشِ جایگزین", readonly=True)
    published_on = fields.Datetime("زمانِ اعلامِ عمومی", readonly=True)
    check_ids = fields.One2many('ikiku.booking.check', 'booking_id', string="بازبینی‌ها")

    date_start_fa = fields.Char(compute='_compute_fa', string="از (شمسی)")
    date_end_fa = fields.Char(compute='_compute_fa', string="تا (شمسی)")

    @api.depends('resource_id', 'date_start', 'employer_business_id.name')
    def _compute_name(self):
        for rec in self:
            rec.name = "%s @ %s — %s" % (
                rec.resource_id.name or '', rec.employer_business_id.name or '',
                format_jalali(rec.date_start))

    @api.depends('date_start', 'date_end')
    def _compute_fa(self):
        for rec in self:
            rec.date_start_fa = format_jalali(rec.date_start)
            rec.date_end_fa = format_jalali(rec.date_end) if rec.date_end else "بدون پایان"

    @api.depends('venue_public', 'date_start', 'state')
    def _compute_venue_disclosed(self):
        today = fields.Date.context_today(self)
        for rec in self:
            started = bool(rec.date_start and rec.date_start <= today)
            rec.venue_disclosed = bool(rec.venue_public or started)

    @api.constrains('resource_id', 'demand_id')
    def _check_not_own_business(self):
        """A person who holds a business and also looks for work (operator, 2026-09-16) is
        never booked at their own business through iKiKu: the public register would record
        a commitment nobody else made."""
        for rec in self:
            holder = rec.demand_id.business_id.partner_id.commercial_partner_id
            if holder and rec.resource_id.partner_id.commercial_partner_id == holder:
                raise ValidationError("دارندهٔ یک کسب‌وکار از راهِ ایکیکو در همان کسب‌وکار گمارده نمی‌شود.")

    @api.model
    def _ikiku_flag_own_bookings(self):
        """Bookings made before the rule above: flagged for staff, never cancelled here,
        because a public booking may only be withdrawn publicly and with a reason."""
        flagged = self.browse()
        for rec in self.search([]):
            holder = rec.demand_id.business_id.partner_id.commercial_partner_id
            if holder and rec.resource_id.partner_id.commercial_partner_id == holder:
                rec.message_post(body="نیرو دارندهٔ همین کسب‌وکار است. این گمارش پیش از قاعدهٔ منعِ آن "
                                      "ثبت شده؛ اگر باید برداشته شود، با دلیل لغو کنید تا عمومی بماند.")
                flagged |= rec
        return flagged

    @api.model_create_multi
    def create(self, vals_list):
        bookings = super().create(vals_list)
        for booking in bookings:
            booking.public_ref = 'IK-%06d' % booking.id
            booking.published_on = fields.Datetime.now()
            if booking.availability_id:
                booking.availability_id.state = 'booked'
            booking._schedule_checks()
            booking.message_post(
                body="گمارش تأیید و همان لحظه عمومی شد: %s" % booking.public_summary())
        return bookings

    # ------------------------------------------------------------ publication
    def public_summary(self):
        """What the open web is told. No venue, no hours, unless disclosed."""
        self.ensure_one()
        where = self.employer_business_id.name if self.venue_disclosed \
            else (self.province_id.name or '')
        return "%s — از %s تا %s — %s" % (
            self.resource_id.name or '', self.date_start_fa, self.date_end_fa, where)

    def public_payload(self):
        self.ensure_one()
        data = {
            'ref': self.public_ref,
            'resource': self.resource_id.name,
            'resource_slug': self.resource_id.slug,
            'date_start_fa': self.date_start_fa,
            'date_end_fa': self.date_end_fa,
            'province': self.province_id.name,
            'state': self.state,
            'cancelled': self.state == 'cancelled',
            'cancel_reason': self.cancel_reason or '',
        }
        # The venue is the one field the ratified article withholds.
        data['business'] = self.employer_business_id.name if self.venue_disclosed else False
        return data

    # ----------------------------------------------------------- the re-check
    def _schedule_checks(self):
        Check = self.env['ikiku.booking.check']
        for booking in self:
            for key, _label in CHECKPOINTS:
                due = fields.Date.subtract(booking.date_start, days=CHECKPOINT_DAYS[key])
                Check.create({'booking_id': booking.id, 'checkpoint': key, 'due_date': due})

    def action_flag_at_risk(self, reason=''):
        self.ensure_one()
        self.write({'state': 'at_risk'})
        self.message_post(body="در معرضِ خطر: %s" % (reason or "بازبینی ناموفق بود."))
        return self.env['ikiku.proposal'].build_for_demand(self.demand_id)

    def action_cancel(self, reason):
        """Cancellation is never silent. That is the whole point of publishing."""
        self.ensure_one()
        if not reason:
            raise UserError(
                "لغو بدونِ دلیل ممکن نیست. تعهدی که عمومی اعلام شده، عمومی هم پس گرفته می‌شود.")
        if self.availability_id:
            self.availability_id.state = 'open'
        self.write({'state': 'cancelled', 'cancel_reason': reason,
                    'cancelled_by_id': self.env.user.partner_id.id})
        self.message_post(body="لغو شد — %s" % reason)


class IkikuBookingCheck(models.Model):
    """T-14, T-3, T-24: is this person still on schedule?

    Each checkpoint becomes a task in the call-centre project. A failed check
    reopens the ranked pool rather than leaving a business to find out on the day.
    """
    _name = 'ikiku.booking.check'
    _description = "بازبینیِ پیش از شروع"
    _order = 'due_date'

    booking_id = fields.Many2one('ikiku.booking', required=True, ondelete='cascade',
                                 index=True, string="گمارش")
    checkpoint = fields.Selection(CHECKPOINTS, required=True, string="ایست")
    due_date = fields.Date("سررسید", required=True, index=True)
    state = fields.Selection([
        ('pending', "در انتظار"),
        ('confirmed', "تأیید شد"),
        ('failed', "ناموفق"),
    ], default='pending', required=True, string="وضعیت")
    task_id = fields.Many2one('project.task', string="کارِ مرکز تماس", readonly=True)
    note = fields.Text("یادداشت")

    _check_uniq = models.Constraint('UNIQUE(booking_id, checkpoint)',
                                    "هر ایست برای هر گمارش یک بار.")

    def action_confirm(self, note=''):
        self.write({'state': 'confirmed', 'note': note})
        for check in self:
            if check.task_id:
                check.task_id.state = '1_done'

    def action_fail(self, note=''):
        self.write({'state': 'failed', 'note': note})
        for check in self:
            check.booking_id.action_flag_at_risk(note)

    @api.model
    def _cron_raise_due_checks(self):
        """Open a call-centre task for every check that has come due."""
        project = self.env.ref('ikiku_match.project_call_centre', raise_if_not_found=False)
        today = fields.Date.context_today(self)
        due = self.search([('state', '=', 'pending'), ('due_date', '<=', today),
                           ('task_id', '=', False),
                           ('booking_id.state', 'in', ('confirmed', 'at_risk'))])
        for check in due:
            vals = {
                'name': "بازبینی %s — %s" % (
                    dict(CHECKPOINTS)[check.checkpoint], check.booking_id.name),
                'description': "آیا این نیرو هنوز طبقِ برنامه است؟ اگر نه، ایست را ناموفق کنید "
                               "تا جایگزین پیشنهاد شود.",
            }
            if project:
                vals['project_id'] = project.id
            check.task_id = self.env['project.task'].create(vals)
        return len(due)

    @api.model
    def _cron_start_and_close_bookings(self):
        """Move bookings through their own calendar, and disclose the venue on
        the day work begins -- which is exactly when بند ۷ stops withholding it."""
        today = fields.Date.context_today(self)
        Booking = self.env['ikiku.booking']
        Booking.search([('state', '=', 'confirmed'), ('date_start', '<=', today),
                        ('date_end', '>=', today)]).write({'state': 'in_progress'})
        Booking.search([('state', 'in', ('confirmed', 'in_progress')),
                        ('date_end', '<', today)]).write({'state': 'done'})
