# Part of iKiKu. Licensed under AGPL-3.0.
"""When a resource is free -- entered in Jalali, stored Gregorian.

This is `counterparty` class under بند ۷: verified businesses may see it, the
open web may not. Knowing when a named person is free is a schedule; the
manifest keeps schedules off the public page.
"""
from odoo import api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.ikiku_base.models.jalali import format_jalali


class IkikuAvailability(models.Model):
    _name = 'ikiku.availability'
    _description = "بازهٔ در دسترس بودن"
    _order = 'date_start'

    resource_id = fields.Many2one('ikiku.resource', required=True, index=True,
                                  ondelete='cascade', string="نیرو")
    date_start = fields.Date("از تاریخ", required=True)
    date_end = fields.Date("تا تاریخ", required=True)
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
            rec.date_end_fa = format_jalali(rec.date_end)

    @api.constrains('date_start', 'date_end')
    def _check_order(self):
        for rec in self:
            if rec.date_end < rec.date_start:
                raise ValidationError("تاریخ پایان نمی‌تواند پیش از تاریخ آغاز باشد.")

    @api.constrains('resource_id', 'date_start', 'date_end')
    def _check_no_overlap(self):
        for rec in self:
            clash = self.search_count([
                ('id', '!=', rec.id),
                ('resource_id', '=', rec.resource_id.id),
                ('date_start', '<=', rec.date_end),
                ('date_end', '>=', rec.date_start),
            ])
            if clash:
                raise ValidationError(
                    "این بازه با بازهٔ دیگری از همین نیرو هم‌پوشانی دارد. "
                    "یک نفر نمی‌تواند هم‌زمان دو جا آزاد باشد.")

    def covers(self, date_from, date_to):
        self.ensure_one()
        return self.date_start <= date_from and self.date_end >= date_to
