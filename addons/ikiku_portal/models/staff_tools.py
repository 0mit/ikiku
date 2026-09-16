# Part of iKiKu. Licensed under AGPL-3.0.
"""What staff do for people who cannot do it alone.

ikiku.staff.account  create a portal account without an SMS code (operator, D-8).
                     The number is written unproven and marked as staff-written, so
                     the owner of that SIM opens this account the first time they
                     sign in with a code, and it becomes proven then.
ikiku.mobile.change  change a person's number (operator, D-7 A): only after the
                     national ID on their card matches the salted hash on record.
                     The digits are hashed on the way in and never stored.
Both leave a chatter entry naming the staff member, never printing the number.
"""
import hmac

from odoo import api, fields, models
from odoo.exceptions import UserError


class IkikuStaffAccount(models.TransientModel):
    _name = 'ikiku.staff.account'
    _description = "ساختِ حساب به دستِ همکار"

    name = fields.Char("نام و نام خانوادگی", required=True)
    mobile = fields.Char("شمارهٔ موبایل", required=True)
    role = fields.Selection([('ki', "دنبالِ کار"), ('ku', "کافه یا رستوران")], string="برای",
                            required=True, default='ki')
    business_name = fields.Char("نامِ کافه یا رستوران")

    def action_create(self):
        self.ensure_one()
        Partner = self.env['res.partner'].sudo().with_context(active_test=False)
        mobile = Partner.normalise_mobile(self.mobile)
        if Partner.search_count([('ikiku_mobile', '=', mobile)], limit=1):
            raise UserError("این شماره روی حسابِ دیگری هست. همان حساب را پیدا کنید؛ حسابِ دوم ساخته نشد.")
        if self.role == 'ku' and not (self.business_name or '').strip():
            raise UserError("نامِ کافه یا رستوران را بنویسید.")
        partner = Partner.create({'name': self.name.strip(), 'ikiku_mobile': mobile,
                                  'ikiku_mobile_set_by_id': self.env.user.id})
        user = self.env['ikiku.mobile.challenge'].sudo()._portal_user_for(partner)
        if self.role == 'ki':
            self.env['ikiku.resource'].sudo().create({'partner_id': partner.id})
            user.group_ids = [(4, self.env.ref('ikiku_base.group_ikiku_resource').id)]
        else:
            self.env['ikiku.business'].sudo().create({'partner_id': partner.id,
                                                      'name': self.business_name.strip()})
            user.group_ids = [(4, self.env.ref('ikiku_base.group_ikiku_business').id)]
        partner.message_post(body="حساب به دستِ %s ساخته شد، بدونِ کدِ پیامک. شماره تا وقتی صاحبش "
                                  "با کد وارد نشود تأییدنشده می‌ماند." % self.env.user.name)
        return {'type': 'ir.actions.act_window', 'res_model': 'res.partner', 'res_id': partner.id,
                'view_mode': 'form', 'target': 'current'}


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
