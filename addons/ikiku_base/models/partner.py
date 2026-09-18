# Part of iKiKu. Licensed under AGPL-3.0.
"""Identity and standing on res.partner.

Phone is the establishing anchor. ikiku_mobile is the number a person signs in with and
the only place it is written (by an SMS code or by staff tools, never by a form); Odoo's
`phone` is a copy of it on every partner that has one, so the number staff see, search
and send SMS to is the proven one (operator, 2026-09-16). A different phone on such a
partner is refused, and a landline found there is kept on a child contact.

The national ID is NEVER stored -- only a
salted hash, enough to detect a duplicate person and to record that someone
checked the card, and not enough to reconstruct the number. A verified national
ID database of named workers is the single most stealable thing this co-op
could own, so it does not own one.
"""
import hashlib
import re

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .jalali import to_latin_digits

IR_MOBILE = re.compile(r'^(?:\+98|0098|0)?9\d{9}$')

# Standing, the whole rule (بند ۸). Pages and help render these, never a copy of them.
STANDING_VERIFIED = 1.0        # identity checked by staff
STANDING_PER_SUPPORTED = 0.25  # each claim someone else confirmed
STANDING_MAX = 5.0

PHONE_SYNC = 'ikiku_phone_sync'
OTHER_PHONE_NAME = "تلفنِ دیگر"
PHONE_REFUSED = ("این تلفن همان شمارهٔ ورودِ این شخص است و اینجا عوض نمی‌شود. برای عوض کردنش "
                 "«تغییرِ شمارهٔ موبایل» را بزنید؛ تلفنِ دیگر را روی یک مخاطبِ زیرمجموعه بنویسید.")
MOBILE_BY_TOOLS = "شمارهٔ ورود فقط با کدِ پیامک یا ابزارهای «کمک به آدم‌ها» نوشته می‌شود."


class ResPartner(models.Model):
    _inherit = ['res.partner', 'ikiku.publishable', 'place.located']
    # A person's public face stops at their city unless THEY say otherwise: a neighbourhood is
    # nearly an address, and بند ۷ keeps an address out of public reach -- «هر کس خودش تصمیم
    # می‌گیرد کجای این مرز بایستد، و پیش‌فرضِ ما احتیاط است». The operator chose, 2026-09-18,
    # that a person may give their neighbourhood to be shown; nobody else decides it for them.
    _place_public_kinds = ('city', 'village', 'province')
    _place_public_kinds_shown = ('neighbourhood', 'district', 'city', 'village', 'province')

    ikiku_show_neighbourhood = fields.Boolean(
        "محله‌ام دیده شود", default=False, copy=False,
        help="خودِ شخص خواسته محله‌اش دیده شود. بدونِ آن، فقط شهرش عمومی است — بند ۷.")
    ikiku_mobile = fields.Char("موبایل (لنگرِ هویت)", index=True, copy=False)
    # بند ۷: mail tracks `phone`, which would copy every number into the chatter.
    phone = fields.Char(tracking=False)
    ikiku_mobile_verified_on = fields.Datetime(
        "تأییدِ موبایل", copy=False, readonly=True, groups='ikiku_base.group_ikiku_staff',
        help="وقتی صاحبِ شماره کدِ پیامک را وارد کرد. مالکیتِ شماره را نشان می‌دهد، نه هویت را.")
    ikiku_nid_hash = fields.Char("اثرِ کدِ ملی", index=True, copy=False, groups='ikiku_base.group_ikiku_staff',
                                 help="درهم‌سازیِ نمک‌دار. خودِ کدِ ملی هرگز ذخیره نمی‌شود.")
    ikiku_nid_checked_on = fields.Date("تاریخِ بررسیِ کدِ ملی", groups='ikiku_base.group_ikiku_staff')
    # Where a person is, since 2026-09-18: `place_id` of place.located is the one field
    # anybody sets, and these two are read off the tree above it. They keep their names
    # because every page, filter and report that asks for a province or a city still asks
    # with them -- what changed is that neither can drift from the other any more.
    ikiku_province_id = fields.Many2one('place.node', related='place_province_id', store=True,
                                        string="استان", readonly=True)
    ikiku_city = fields.Char(related='place_city_name', store=True, string="شهر", readonly=True)
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

    @api.model
    def _ikiku_same_number(self, raw, mobile):
        try:
            return bool(raw) and bool(mobile) and self.normalise_mobile(raw) == mobile
        except ValidationError:
            return False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            mobile = vals.get('ikiku_mobile')
            if not mobile:
                continue
            if not self.env.su:
                raise AccessError(MOBILE_BY_TOOLS)
            if vals.get('phone') and not self._ikiku_same_number(vals['phone'], mobile):
                raise UserError(PHONE_REFUSED)
            vals['phone'] = mobile
        return super().create(vals_list)

    def write(self, vals):
        """A number changed without its proof is no longer the number that was proven, and
        the phone follows the number."""
        if 'ikiku_mobile' in vals and not self.env.su:
            raise AccessError(MOBILE_BY_TOOLS)
        if 'phone' in vals and not self.env.context.get(PHONE_SYNC):
            if 'ikiku_mobile' in vals:
                if vals['ikiku_mobile'] and vals['phone'] \
                        and not self._ikiku_same_number(vals['phone'], vals['ikiku_mobile']):
                    raise UserError(PHONE_REFUSED)
                vals = {key: value for key, value in vals.items() if key != 'phone'}
            else:
                anchored = self.filtered('ikiku_mobile')
                if anchored:
                    for partner in anchored:
                        if not self._ikiku_same_number(vals['phone'], partner.ikiku_mobile):
                            raise UserError(PHONE_REFUSED)
                    rest = {key: value for key, value in vals.items() if key != 'phone'}
                    if self - anchored:
                        (self - anchored).write(vals)
                    if rest:
                        anchored.write(rest)
                    return True
        before = {partner.id: partner.ikiku_mobile for partner in self} if 'ikiku_mobile' in vals else {}
        if 'ikiku_mobile' in vals and 'ikiku_mobile_verified_on' not in vals:
            changed = self.filtered(lambda partner: partner.ikiku_mobile != vals['ikiku_mobile'])
            if changed:
                super(ResPartner, changed.sudo()).write({'ikiku_mobile_verified_on': False})
        result = super().write(vals)
        if before:
            self._ikiku_copy_phone(before)
        return result

    def _ikiku_copy_phone(self, before):
        """After ikiku_mobile changed: phone becomes the new number, or is cleared when the
        number was taken away and the phone was that number."""
        for partner in self:
            old, new = before.get(partner.id), partner.ikiku_mobile
            if old == new and (not new or partner.phone == new):
                continue
            quiet = partner.sudo().with_context(mail_notrack=True, **{PHONE_SYNC: True})
            if new:
                if partner.phone != new:
                    quiet._ikiku_keep_other_phone(also_not=old)
                    super(ResPartner, quiet).write({'phone': new})
            elif old and self._ikiku_same_number(partner.phone, old):
                super(ResPartner, quiet).write({'phone': False})

    def _ikiku_keep_other_phone(self, also_not=None):
        """A phone that is not the login number (a landline, an old number typed by staff)
        moves to a child contact instead of being overwritten."""
        for partner in self.sudo():
            phone = partner.phone
            if not phone or self._ikiku_same_number(phone, partner.ikiku_mobile) \
                    or (also_not and self._ikiku_same_number(phone, also_not)):
                continue
            self.sudo().with_context(mail_notrack=True, **{PHONE_SYNC: True}).create({
                'name': OTHER_PHONE_NAME, 'parent_id': partner.id, 'type': 'other', 'phone': phone})
            partner.message_post(body="تلفنی که روی این پرونده بود به مخاطبِ «%s» منتقل شد تا تلفنِ "
                                      "پرونده همان شمارهٔ ورود باشد." % OTHER_PHONE_NAME)

    @api.depends('ikiku_is_verified', 'ikiku_assertion_ids.state')
    def _compute_ikiku_standing(self):
        """Bounded and readable. No hidden formula -- بند ۸ and the 'never' list."""
        for partner in self:
            supported = partner.ikiku_assertion_ids.filtered(lambda a: a.state == 'supported')
            standing = (STANDING_VERIFIED if partner.ikiku_is_verified else 0.0) \
                + STANDING_PER_SUPPORTED * len(supported)
            partner.ikiku_standing = min(standing, STANDING_MAX)

    @api.model
    def normalise_mobile(self, raw):
        """+98 canonical form, so the same person cannot arrive twice."""
        if not raw:
            return False
        # [0-9] matches Latin digits only: a number typed in Persian digits was stripped
        # to nothing and refused, so digits are made Latin first.
        digits = re.sub(r'[^0-9+]', '', to_latin_digits(raw))
        if not IR_MOBILE.match(digits):
            raise ValidationError("شمارهٔ موبایل ایران معتبر نیست: %s" % raw)
        return '+98' + digits[-10:]

    @api.model
    def hash_national_id(self, nid):
        """One-way. The salt lives in system parameters, not in the code."""
        if not nid:
            return False
        nid = re.sub(r'[^0-9]', '', to_latin_digits(nid))
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

    def _place_public_kinds_of(self):
        self.ensure_one()
        return self._place_public_kinds_shown if self.ikiku_show_neighbourhood else self._place_public_kinds

    @api.depends('place_id', 'place_id.parent_id', 'place_id.kind', 'ikiku_show_neighbourhood')
    def _compute_place_parts(self):
        return super()._compute_place_parts()
