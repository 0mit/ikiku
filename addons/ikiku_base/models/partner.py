# Part of iKiKu. Licensed under AGPL-3.0.
"""Identity and standing on res.partner.

Phone is the establishing anchor. The national ID is NEVER stored -- only a
salted hash, enough to detect a duplicate person and to record that someone
checked the card, and not enough to reconstruct the number. A verified national
ID database of named workers is the single most stealable thing this co-op
could own, so it does not own one.
"""
import hashlib
import re

from odoo import api, fields, models
from odoo.exceptions import ValidationError

IR_MOBILE = re.compile(r'^(?:\+98|0098|0)?9\d{9}$')


class ResPartner(models.Model):
    _inherit = ['res.partner', 'ikiku.publishable']

    ikiku_mobile = fields.Char("موبایل (لنگرِ هویت)", index=True, copy=False)
    ikiku_nid_hash = fields.Char("اثرِ کدِ ملی", index=True, copy=False, groups='ikiku_base.group_ikiku_staff',
                                 help="درهم‌سازیِ نمک‌دار. خودِ کدِ ملی هرگز ذخیره نمی‌شود.")
    ikiku_nid_checked_on = fields.Date("تاریخِ بررسیِ کدِ ملی", groups='ikiku_base.group_ikiku_staff')
    ikiku_province_id = fields.Many2one('ikiku.province', string="استان")
    ikiku_city = fields.Char("شهر")
    ikiku_is_verified = fields.Boolean("هویت تأییدشده", default=False, tracking=True)
    ikiku_assertion_ids = fields.One2many('ikiku.assertion', 'resource_id', string="ادعاها")
    ikiku_standing = fields.Float(
        "اعتبار", compute='_compute_ikiku_standing', store=True,
        help="از ادعاهای پشتیبانی‌شده به دست می‌آید و راهِ رسیدن به آن پیداست. "
             "با پول تغییر نمی‌کند — بند ۸.")

    _ikiku_mobile_uniq = models.Constraint(
        'UNIQUE(ikiku_mobile)', "این شمارهٔ موبایل قبلاً ثبت شده است.")
    _ikiku_nid_uniq = models.Constraint(
        'UNIQUE(ikiku_nid_hash)', "این کدِ ملی قبلاً ثبت شده است.")

    @api.depends('ikiku_is_verified', 'ikiku_assertion_ids.state')
    def _compute_ikiku_standing(self):
        """Bounded and readable. No hidden formula -- بند ۸ and the 'never' list."""
        for partner in self:
            supported = partner.ikiku_assertion_ids.filtered(lambda a: a.state == 'supported')
            standing = (1.0 if partner.ikiku_is_verified else 0.0) + 0.25 * len(supported)
            partner.ikiku_standing = min(standing, 5.0)

    @api.model
    def normalise_mobile(self, raw):
        """+98 canonical form, so the same person cannot arrive twice."""
        if not raw:
            return False
        digits = re.sub(r'[^0-9+]', '', raw)
        if not IR_MOBILE.match(digits):
            raise ValidationError("شمارهٔ موبایل ایران معتبر نیست: %s" % raw)
        return '+98' + digits[-10:]

    @api.model
    def hash_national_id(self, nid):
        """One-way. The salt lives in system parameters, not in the code."""
        if not nid:
            return False
        nid = re.sub(r'[^0-9]', '', nid)
        if len(nid) != 10:
            raise ValidationError("کدِ ملی باید ده رقم باشد.")
        salt = self.env['ir.config_parameter'].sudo().get_param('ikiku.nid_salt')
        if not salt:
            raise ValidationError(
                "پارامترِ ikiku.nid_salt تنظیم نشده است. بدون آن کدِ ملی درهم‌سازی نمی‌شود.")
        return hashlib.sha256((salt + nid).encode()).hexdigest()

    @api.onchange('ikiku_mobile')
    def _onchange_ikiku_mobile(self):
        if self.ikiku_mobile:
            self.ikiku_mobile = self.normalise_mobile(self.ikiku_mobile)
