# Part of iKiKu. Licensed under AGPL-3.0.
"""What staff do for people who cannot do it alone.

ikiku.staff.account  create a portal account without an SMS code (operator, D-8).
                     The number is written unproven and marked as staff-written, so
                     the owner of that SIM opens this account the first time they
                     sign in with a code, and it becomes proven then.
ikiku.staff.role     give an existing account its second side (operator, 2026-09-16:
                     one person may look for work and hold a business).
ikiku.mobile.change  change a person's number (operator, D-7 A): only after the
                     national ID on their card matches the salted hash on record.
                     The digits are hashed on the way in and never stored.
Both leave a chatter entry naming the staff member, never printing the number.
"""
import hmac

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from odoo.addons.ikiku_portal.models.res_partner import ROLE_LABEL


class IkikuStaffAccount(models.TransientModel):
    _name = 'ikiku.staff.account'
    _description = "ساختِ حساب به دستِ همکار"

    name = fields.Char("نام و نام خانوادگی", required=True)
    mobile = fields.Char("شمارهٔ موبایل", required=True)
    role = fields.Selection([('ki', "دنبالِ کار"), ('ku', "کافه یا رستوران"), ('both', "هر دو")],
                            string="برای", required=True, default='ki')
    business_name = fields.Char("نامِ کافه یا رستوران")
    existing_partner_ids = fields.Many2many('res.partner', string="مخاطب‌هایی با همین تلفن",
                                            compute='_compute_existing_partner_ids')
    match_action = fields.Selection([
        ('adopt', "حساب روی همین مخاطب ساخته شود"),
        ('new', "مخاطبِ تازه ساخته شود"),
    ], string="با مخاطبِ موجود چه کنیم؟")

    def _existing_partners(self, mobile):
        """Contacts staff already have with this phone but no login number: a typed phone is
        not proof, so staff choose; an SMS never takes such a contact over."""
        Partner = self.env['res.partner'].sudo().with_context(active_test=False)
        # phone_sanitized is empty for a contact with no country, so the last digits find the
        # candidates and the same normalisation as sign-in decides.
        candidates = Partner.search([('ikiku_mobile', '=', False), '|', ('phone_sanitized', '=', mobile),
                                     ('phone', 'ilike', mobile[-7:])])
        return candidates.filtered(lambda partner: Partner._ikiku_same_number(partner.phone, mobile)
                                   and not partner.user_ids.filtered(lambda user: not user.share))

    @api.depends('mobile')
    def _compute_existing_partner_ids(self):
        for wizard in self:
            try:
                mobile = self.env['res.partner'].normalise_mobile(wizard.mobile)
            except ValidationError:
                mobile = False
            wizard.existing_partner_ids = self._existing_partners(mobile) if mobile else False

    def action_create(self):
        self.ensure_one()
        Partner = self.env['res.partner'].sudo().with_context(active_test=False)
        mobile = Partner.normalise_mobile(self.mobile)
        if Partner.search_count([('ikiku_mobile', '=', mobile)], limit=1):
            raise UserError("این شماره روی حسابِ دیگری هست. اگر همان شخص نقشِ دوم می‌خواهد، «دادنِ نقشِ دوم» "
                            "را بزنید؛ حسابِ دوم ساخته نشد.")
        if self.role in ('ku', 'both') and not (self.business_name or '').strip():
            raise UserError("نامِ کافه یا رستوران را بنویسید.")
        existing = self._existing_partners(mobile)
        if existing and not self.match_action:
            raise UserError("مخاطبی با همین تلفن هست: %s. یکی را انتخاب کنید: «حساب روی همین مخاطب» یا "
                            "«مخاطبِ تازه»." % "، ".join(existing.mapped('display_name')))
        if existing and self.match_action == 'adopt':
            if len(existing) != 1:
                raise UserError("بیش از یک مخاطب با همین تلفن هست؛ «مخاطبِ تازه» را بزنید یا اول تکراری‌ها "
                                "را یکی کنید.")
            partner = existing
            partner.write({'ikiku_mobile': mobile, 'ikiku_mobile_set_by_id': self.env.user.id})
            partner.message_post(body="حساب روی مخاطبِ موجود به دستِ %s ساخته شد." % self.env.user.name)
        else:
            partner = Partner.create({'name': self.name.strip(), 'ikiku_mobile': mobile,
                                      'ikiku_mobile_set_by_id': self.env.user.id})
        for role in (('ki', 'ku') if self.role == 'both' else (self.role,)):
            partner._ikiku_grant_role(role, business_name=self.business_name)
        partner.message_post(body="حساب به دستِ %s ساخته شد، بدونِ کدِ پیامک. شماره تا وقتی صاحبش "
                                  "با کد وارد نشود تأییدنشده می‌ماند." % self.env.user.name)
        return {'type': 'ir.actions.act_window', 'res_model': 'res.partner', 'res_id': partner.id,
                'view_mode': 'form', 'target': 'current'}


class IkikuStaffRole(models.TransientModel):
    _name = 'ikiku.staff.role'
    _description = "دادنِ نقشِ دوم به دستِ همکار"

    partner_id = fields.Many2one('res.partner', string="شخص", required=True)
    role = fields.Selection([('ki', "دنبالِ کار"), ('ku', "کافه یا رستوران")], string="نقشِ تازه",
                            required=True)
    business_name = fields.Char("نامِ کافه یا رستوران")

    def action_apply(self):
        self.ensure_one()
        partner = self.partner_id.sudo()
        if not partner.ikiku_mobile:
            raise UserError("این شخص شمارهٔ موبایل ندارد. اول با «ساختِ حساب» برایش حساب بسازید.")
        if self.role == 'ki':
            has = self.env['ikiku.resource'].sudo().search_count([('partner_id', '=', partner.id)], limit=1)
        else:
            has = self.env['ikiku.business'].sudo().search_count(
                [('partner_id', '=', partner.commercial_partner_id.id)], limit=1)
        if has and self.role == 'ki':
            raise UserError("این حساب این نقش را دارد.")
        # A holder may hold several businesses: with a name, another one is added.
        partner._ikiku_grant_role(self.role, business_name=self.business_name, another=bool(has))
        partner.message_post(body="نقشِ «%s» به دستِ %s به همین حساب اضافه شد."
                                  % (ROLE_LABEL[self.role], self.env.user.name))
        return {'type': 'ir.actions.act_window_close'}


class IkikuMobileChange(models.TransientModel):
    _name = 'ikiku.mobile.change'
    _description = "تغییرِ شمارهٔ موبایل به دستِ همکار"

    partner_id = fields.Many2one('res.partner', string="شخص", required=True)
    new_mobile = fields.Char("شمارهٔ تازه", required=True)
    national_id = fields.Char("کدِ ملی از روی کارت", help="روی کارت دیده شود. رقم‌ها نگه داشته نمی‌شوند.")
    nid_hash = fields.Char(readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._hash_national_id(vals)
        return super().create(vals_list)

    def write(self, vals):
        self._hash_national_id(vals)
        return super().write(vals)

    @api.model
    def _hash_national_id(self, vals):
        """The typed digits become the salted hash here and go no further."""
        if vals.get('national_id'):
            vals['nid_hash'] = self.env['res.partner'].sudo().hash_national_id(vals['national_id'])
        vals.pop('national_id', None)

    def action_apply(self):
        self.ensure_one()
        partner = self.partner_id.sudo()
        if not partner.ikiku_nid_hash:
            raise UserError("برای این شخص کدِ ملی ثبت نشده است. نخست کارتِ ملی را بررسی و ثبت کنید؛ "
                            "بدونِ آن شماره عوض نمی‌شود.")
        if not self.nid_hash or not hmac.compare_digest(self.nid_hash, partner.ikiku_nid_hash):
            raise UserError("کدِ ملی با پرونده یکی نیست. شماره عوض نشد.")
        Partner = self.env['res.partner'].sudo().with_context(active_test=False)
        mobile = Partner.normalise_mobile(self.new_mobile)
        others = Partner.search([('ikiku_mobile', '=', mobile), ('id', '!=', partner.id)])
        if others.filtered('ikiku_mobile_verified_on'):
            raise UserError("این شماره برای حسابِ دیگری تأیید شده است.")
        for holder in others:
            holder.ikiku_mobile = False
            holder.message_post(body="شمارهٔ موبایلِ تأییدنشدهٔ این حساب برداشته شد: همکارِ ایکیکو "
                                     "آن را پس از بررسیِ کدِ ملی به حسابِ دیگری داد.")
        partner.write({'ikiku_mobile': mobile, 'ikiku_mobile_verified_on': False,
                       'ikiku_mobile_set_by_id': self.env.user.id})
        partner.user_ids.filtered('share')._action_revoke_all_devices()
        partner.message_post(body="شمارهٔ موبایل به دستِ %s و پس از بررسیِ کدِ ملی عوض شد. همهٔ ورودهای "
                                  "قبلی بسته شد؛ صاحبِ شمارهٔ تازه با کدِ پیامک وارد می‌شود."
                                  % self.env.user.name)
        return {'type': 'ir.actions.act_window_close'}
