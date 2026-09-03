# Part of iKiKu. Licensed under AGPL-3.0.
"""Seasons drive F&B demand, and in Iran they are not Gregorian.

Nowruz is fixed in the Jalali calendar. Ramadan and Muharram are Hijri and drift
about eleven days earlier each Gregorian year, and Iran's determination of them
is observational -- so a computed window is a DRAFT that a human confirms. The
`confirmed` flag on a window is the difference between arithmetic and fact.
"""
from odoo import api, fields, models
from odoo.exceptions import ValidationError

from .jalali import jalali_to_gregorian, gregorian_to_jalali


class IkikuSeason(models.Model):
    _name = 'ikiku.season'
    _description = "فصل تقاضا"
    _order = 'sequence, name'

    name = fields.Char("نام", required=True)
    sequence = fields.Integer(default=10)
    calendar = fields.Selection(
        [('jalali', "هجری شمسی"), ('hijri', "هجری قمری"), ('gregorian', "میلادی")],
        string="تقویم", required=True, default='jalali')
    start_month = fields.Integer("ماه آغاز", required=True)
    start_day = fields.Integer("روز آغاز", required=True)
    duration_days = fields.Integer("طول (روز)", required=True, default=1)
    province_ids = fields.Many2many('ikiku.province', string="استان‌ها",
                                    help="خالی یعنی سراسر کشور.")
    demand_factor = fields.Float(
        "ضریب تقاضا", default=1.0,
        help="بزرگ‌تر از ۱ یعنی اوج تقاضا، کوچک‌تر از ۱ یعنی کم‌باری. "
             "در رتبه‌بندی استفاده می‌شود و در پیشنهاد نمایش داده می‌شود.")
    window_ids = fields.One2many('ikiku.season.window', 'season_id', string="بازه‌ها")
    note = fields.Text("توضیح")

    @api.constrains('start_month', 'start_day', 'duration_days')
    def _check_bounds(self):
        for rec in self:
            if not 1 <= rec.start_month <= 12:
                raise ValidationError("ماه باید بین ۱ تا ۱۲ باشد.")
            if not 1 <= rec.start_day <= 31:
                raise ValidationError("روز باید بین ۱ تا ۳۱ باشد.")
            if rec.duration_days < 1:
                raise ValidationError("طول فصل باید دست‌کم یک روز باشد.")

    def action_materialise(self, jalali_year=None):
        """Turn the rule into concrete dates for one Jalali year.

        Hijri seasons are materialised as `confirmed=False`: the arithmetic is a
        starting point, never the authority.
        """
        Window = self.env['ikiku.season.window']
        today = fields.Date.context_today(self)
        jy_now = gregorian_to_jalali(today.year, today.month, today.day)[0]
        jy = jalali_year or jy_now
        created = Window.browse()
        for season in self:
            if season.calendar != 'jalali':
                # Hijri/Gregorian rules need their own reckoning; the window is
                # opened empty for a human to fill rather than guessed at.
                created |= Window.create({
                    'season_id': season.id, 'jalali_year': jy,
                    'date_start': False, 'date_end': False, 'confirmed': False,
                })
                continue
            gy, gm, gd = jalali_to_gregorian(jy, season.start_month, season.start_day)
            start = fields.Date.to_date('%04d-%02d-%02d' % (gy, gm, gd))
            created |= Window.create({
                'season_id': season.id, 'jalali_year': jy,
                'date_start': start,
                'date_end': fields.Date.add(start, days=season.duration_days - 1),
                'confirmed': True,
            })
        return created


class IkikuSeasonWindow(models.Model):
    _name = 'ikiku.season.window'
    _description = "بازهٔ فصل در یک سال"
    _order = 'date_start desc'

    season_id = fields.Many2one('ikiku.season', required=True, ondelete='cascade', string="فصل")
    jalali_year = fields.Integer("سال شمسی", required=True)
    date_start = fields.Date("از تاریخ")
    date_end = fields.Date("تا تاریخ")
    confirmed = fields.Boolean(
        "تأییدشده", default=False,
        help="بازهٔ قمری با حساب تقویمی به دست می‌آید، اما تعیین آن در ایران رؤیتی است. "
             "تا وقتی انسانی تأیید نکرده، این بازه پیش‌نویس است.")

    @api.model
    def factor_for(self, date_value, province=None):
        """The demand factor in force on a date, in a province. 1.0 if none."""
        if not date_value:
            return 1.0
        domain = [('confirmed', '=', True),
                  ('date_start', '<=', date_value), ('date_end', '>=', date_value)]
        factor = 1.0
        for window in self.search(domain):
            provinces = window.season_id.province_ids
            if provinces and province and province not in provinces:
                continue
            factor *= window.season_id.demand_factor or 1.0
        return factor
