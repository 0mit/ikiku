# Part of iKiKu. Licensed under AGPL-3.0.
from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

ROLE_LABEL = {'ki': "دنبالِ کار", 'ku': "کافه یا رستوران"}


class ResPartner(models.Model):
    _inherit = 'res.partner'

    ikiku_mobile_set_by_id = fields.Many2one(
        'res.users', string="شماره را نوشت", readonly=True, copy=False,
        groups='ikiku_base.group_ikiku_staff',
        help="همکاری که این شماره را نوشت: حسابی که همکار ساخت، یا شماره‌ای که پس از بررسیِ کدِ ملی "
             "عوض کرد. هر کس صاحبِ همین سیم‌کارت باشد و کد را بزند، به همین حساب وارد می‌شود.")
    ikiku_mobile_state = fields.Selection([
        ('proven', "تأییدشده با کدِ پیامک"),
        ('staff', "نوشتهٔ همکار، هنوز تأییدنشده"),
        ('unproven', "تأییدنشده"),
    ], string="وضعِ شمارهٔ ورود", compute='_compute_ikiku_mobile_state', compute_sudo=True,
        groups='ikiku_base.group_ikiku_staff')
    ikiku_mobile_lookup = fields.Char(
        "شمارهٔ ورود", compute='_compute_ikiku_mobile_lookup', search='_search_ikiku_mobile_lookup',
        groups='ikiku_base.group_ikiku_staff',
        help="برای پیدا کردنِ شخص با شماره، به هر شکلی که نوشته شود: ۰۹۱۲…، ۹۸۹۱۲…، +۹۸۹۱۲…")

    @api.depends('ikiku_mobile', 'ikiku_mobile_verified_on', 'ikiku_mobile_set_by_id')
    def _compute_ikiku_mobile_state(self):
        for partner in self:
            if not partner.ikiku_mobile:
                partner.ikiku_mobile_state = False
            elif partner.ikiku_mobile_verified_on:
                partner.ikiku_mobile_state = 'proven'
            elif partner.ikiku_mobile_set_by_id:
                partner.ikiku_mobile_state = 'staff'
            else:
                partner.ikiku_mobile_state = 'unproven'

    def _compute_ikiku_mobile_lookup(self):
        for partner in self:
            partner.ikiku_mobile_lookup = False

    def _search_ikiku_mobile_lookup(self, operator, value):
        # Odoo 19 hands a search method `in` with a list for `=`.
        if operator in ('=', 'ilike'):
            value = [value]
        elif operator != 'in':
            return [('id', '=', 0)]
        mobiles = []
        for raw in value or ():
            try:
                mobiles.append(self.normalise_mobile(raw) if isinstance(raw, str) else False)
            except ValidationError:
                continue
        mobiles = [mobile for mobile in mobiles if mobile]
        return [('ikiku_mobile', 'in', mobiles)] if mobiles else [('id', '=', 0)]

    def write(self, vals):
        """A number anyone else writes is no longer the number a staff member wrote."""
        if 'ikiku_mobile' in vals and 'ikiku_mobile_set_by_id' not in vals:
            changed = self.sudo().filtered(lambda partner: partner.ikiku_mobile != vals['ikiku_mobile']
                                           and partner.ikiku_mobile_set_by_id)
            if changed:
                super(ResPartner, changed).write({'ikiku_mobile_set_by_id': False})
        return super().write(vals)

    def _ikiku_grant_role(self, role, business_name=None):
        """The one way a person gets a side (operator, 2026-09-16: one person may hold both):
        the worker record or the business, and the group that goes with it. Returns the
        record. A staff account never gets a side, and never a second, portal user."""
        self.ensure_one()
        partner = self.sudo()
        if partner.with_context(active_test=False).user_ids.filtered(lambda user: not user.share):
            raise UserError("این شخص حسابِ همکار دارد؛ نقشِ نیرو یا کسب‌وکار به حسابِ همکار داده نمی‌شود.")
        user = self.env['ikiku.mobile.challenge'].sudo()._portal_user_for(partner)
        if role == 'ki':
            Resource = self.env['ikiku.resource'].sudo()
            record = Resource.search([('partner_id', '=', partner.id)], limit=1) \
                or Resource.create({'partner_id': partner.id})
            group = 'ikiku_base.group_ikiku_resource'
        elif role == 'ku':
            holder = partner.commercial_partner_id
            Business = self.env['ikiku.business'].sudo()
            record = Business.search([('partner_id', '=', holder.id)], limit=1)
            if not record:
                if not (business_name or '').strip():
                    raise UserError("نامِ کافه یا رستوران را بنویسید.")
                record = Business.create({'partner_id': holder.id, 'name': business_name.strip()})
            group = 'ikiku_base.group_ikiku_business'
        else:
            raise UserError("نقشِ ناشناخته.")
        user.group_ids = [(4, self.env.ref(group).id)]
        return record
