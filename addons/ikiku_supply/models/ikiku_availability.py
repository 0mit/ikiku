# Part of iKiKu. Licensed under AGPL-3.0.
"""When a resource is free -- entered in Jalali, stored Gregorian.

This is `counterparty` class under بند ۷: verified businesses may see it, the
open web may not. Knowing when a named person is free is a schedule; the
manifest keeps schedules off the public page.
"""
from odoo import api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.ikiku_base.models.jalali import format_jalali

OPEN_END_FA = "بدون پایان"


class IkikuAvailability(models.Model):
    _name = 'ikiku.availability'
    _description = "بازهٔ در دسترس بودن"
    _order = 'date_start'

    resource_id = fields.Many2one('ikiku.resource', required=True, index=True,
                                  ondelete='cascade', string="نیرو")
    date_start = fields.Date("از تاریخ", required=True, default=fields.Date.context_today)
    date_end = fields.Date("تا تاریخ", help="خالی یعنی بدون پایان.")
    work_type_ids = fields.Many2many(
        'ikiku.work.type', string="نوع‌های همکاری",
        help="هر نوعی که این نیرو می‌پذیرد. خالی یعنی نگفته، و از هیچ نیازی کنار گذاشته نمی‌شود.")
    province_id = fields.Many2one('ikiku.province', string="استان", required=True)
    city = fields.Char("شهر")
    can_relocate = fields.Boolean("امکانِ جابه‌جایی", default=False)
    hours_per_week = fields.Integer("ساعت در هفته", default=40)
    shift_node_ids = fields.Many2many('ikiku.spec.node', string="شیفت‌های ممکن",
                                      domain="[('kind', '=', 'attribute')]")
    state = fields.Selection([
        ('open', "آزاد"),
        ('held', "رزروِ موقت"),
        ('booked', "گمارده"),
    ], default='open', required=True, string="وضعیت")

    date_start_fa = fields.Char(compute='_compute_fa', string="از (شمسی)")
    date_end_fa = fields.Char(compute='_compute_fa', string="تا (شمسی)")

    @api.depends('date_start', 'date_end')
    def _compute_fa(self):
        for rec in self:
            rec.date_start_fa = format_jalali(rec.date_start)
            rec.date_end_fa = format_jalali(rec.date_end) if rec.date_end else OPEN_END_FA

    @api.constrains('date_start', 'date_end')
    def _check_order(self):
        for rec in self:
            if rec.date_end and rec.date_end < rec.date_start:
                raise ValidationError("تاریخ پایان نمی‌تواند پیش از تاریخ آغاز باشد.")

    @api.constrains('resource_id', 'date_start', 'date_end')
    def _check_no_overlap(self):
        for rec in self:
            # No end date means no end: it overlaps everything that starts after it.
            domain = [
                ('id', '!=', rec.id),
                ('resource_id', '=', rec.resource_id.id),
                '|', ('date_end', '=', False), ('date_end', '>=', rec.date_start),
            ]
            if rec.date_end:
                domain.append(('date_start', '<=', rec.date_end))
            clash = self.search_count(domain)
            if clash:
                raise ValidationError(
                    "این بازه با بازهٔ دیگری از همین نیرو هم‌پوشانی دارد. "
                    "یک نفر نمی‌تواند هم‌زمان دو جا آزاد باشد.")

    def covers(self, date_from, date_to):
        """Free for the whole window. `date_to` False is an open-ended window, which only
        an open-ended availability covers."""
        self.ensure_one()
        if self.date_start > date_from:
            return False
        if not self.date_end:
            return True
        return bool(date_to) and self.date_end >= date_to

    def accepts(self, work_type):
        """An availability that names no kind of work has not said, so it is not excluded."""
        self.ensure_one()
        return not self.work_type_ids or work_type in self.work_type_ids
