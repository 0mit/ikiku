# Part of iKiKu. Licensed under AGPL-3.0.
"""A declared need: this many people, this window, this province.

A need is never deleted. Every change is tracked in its chatter, and it ends one of two
ways (operator, 2026-09-16): filled, when the business found the people it needed, or
cancelled, which is not complete without a written reason.
"""
from odoo import api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.ikiku_base.models.jalali import format_jalali


class IkikuDemand(models.Model):
    _name = 'ikiku.demand'
    _description = "اعلام نیاز"
    _inherit = ['mail.thread', 'place.located']
    # A need names a place; a card shows at most the neighbourhood it is in, never the street,
    # and only as much as its business chose to show (_place_visibility_of).
    _place_public_kinds = ('neighbourhood', 'district', 'city', 'village', 'province')
    _order = 'date_start'

    name = fields.Char(compute='_compute_name', store=True)
    business_id = fields.Many2one('ikiku.business', required=True, ondelete='cascade',
                                  index=True, string="کسب‌وکار", tracking=True)
    position_id = fields.Many2one('ikiku.position', required=True, string="جایگاه", tracking=True,
                                  domain="[('business_id', '=', business_id)]")
    seats = fields.Integer("تعداد نفر", required=True, default=1, tracking=True)
    date_start = fields.Date("از تاریخ", required=True, tracking=True, default=fields.Date.context_today)
    date_end = fields.Date("تا تاریخ", tracking=True, help="خالی یعنی بدون پایان.")
    work_type_id = fields.Many2one('ikiku.work.type', string="نوعِ همکاری", required=True,
                                   tracking=True, default=lambda self: self._default_work_type())
    # Where the work is, since 2026-09-18: one place from the tree (place.located). A card
    # shows place_public_id -- the neighbourhood, never the street. Moving the work is a
    # change the people already proposed for it are told about, so it is tracked.
    place_id = fields.Many2one('place.node', string="جا", required=True, index=True,
                               ondelete='restrict', tracking=True)
    province_id = fields.Many2one('place.node', related='place_province_id', store=True,
                                  string="استان", readonly=True)
    city = fields.Char(related='place_city_name', store=True, string="شهر", readonly=True)
    business_public_name = fields.Char(related='business_id.public_name', store=True,
                                       string="نامِ عمومیِ کسب‌وکار", readonly=True)
    season_factor = fields.Float("ضریب فصل", compute='_compute_season_factor', store=True)
    note = fields.Text("توضیح")
    state = fields.Selection([
        ('draft', "پیش‌نویس"),
        ('open', "باز"),
        ('proposed', "پیشنهاد داده شد"),
        ('filled', "تکمیل"),
        ('cancelled', "لغو"),
    ], default='draft', required=True, tracking=True, string="وضعیت")
    cancel_reason = fields.Text("دلیلِ لغو", tracking=True,
                                help="بدونِ دلیلِ نوشته‌شده هیچ نیازی لغو نمی‌شود.")
    closed_on = fields.Datetime("زمانِ بستن", readonly=True, copy=False)
    closed_by_id = fields.Many2one('res.users', string="بست", readonly=True, copy=False)

    date_start_fa = fields.Char(compute='_compute_fa', string="از (شمسی)")
    date_end_fa = fields.Char(compute='_compute_fa', string="تا (شمسی)")

    @api.model
    def _default_work_type(self):
        return self.env.ref('ikiku_base.work_type_full_time', raise_if_not_found=False)

    @api.depends('business_id.name', 'position_id.name', 'date_start')
    def _compute_name(self):
        for rec in self:
            rec.name = "%s — %s — %s" % (
                rec.business_id.name or '', rec.position_id.name or '',
                format_jalali(rec.date_start))

    @api.depends('date_start', 'date_end')
    def _compute_fa(self):
        for rec in self:
            rec.date_start_fa = format_jalali(rec.date_start)
            rec.date_end_fa = format_jalali(rec.date_end) if rec.date_end else "بدون پایان"

    @api.depends('date_start', 'province_id')
    def _compute_season_factor(self):
        Window = self.env['ikiku.season.window']
        for rec in self:
            rec.season_factor = Window.factor_for(rec.date_start, rec.province_id)

    @api.constrains('date_start', 'date_end', 'seats')
    def _check_sane(self):
        for rec in self:
            if rec.date_end and rec.date_end < rec.date_start:
                raise ValidationError("تاریخ پایان نمی‌تواند پیش از تاریخ آغاز باشد.")
            if rec.seats < 1:
                raise ValidationError("تعداد نفر باید دست‌کم یک باشد.")

    @api.constrains('state', 'cancel_reason')
    def _check_cancel_reason(self):
        for rec in self:
            if rec.state == 'cancelled' and not (rec.cancel_reason or '').strip():
                raise ValidationError("نیاز بدونِ دلیلِ نوشته‌شده لغو نمی‌شود.")

    def action_open(self):
        self.write({'state': 'open'})

    def _place_visibility_of(self):
        # A need shows as much of its place as its business chose to show of the café's own.
        return self.business_id.place_visibility or 'city'

    @api.depends('place_id', 'place_id.parent_id', 'place_id.kind', 'business_id.place_visibility')
    def _compute_place_parts(self):
        return super()._compute_place_parts()
