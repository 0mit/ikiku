# Part of iKiKu. Licensed under AGPL-3.0.
from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    ikiku_mobile_set_by_id = fields.Many2one(
        'res.users', string="شماره را نوشت", readonly=True, copy=False,
        groups='ikiku_base.group_ikiku_staff',
        help="همکاری که این شماره را نوشت: حسابی که همکار ساخت، یا شماره‌ای که پس از بررسیِ کدِ ملی "
             "عوض کرد. هر کس صاحبِ همین سیم‌کارت باشد و کد را بزند، به همین حساب وارد می‌شود.")

    def write(self, vals):
        """A number anyone else writes is no longer the number a staff member wrote."""
        if 'ikiku_mobile' in vals and 'ikiku_mobile_set_by_id' not in vals:
            changed = self.sudo().filtered(lambda partner: partner.ikiku_mobile != vals['ikiku_mobile']
                                           and partner.ikiku_mobile_set_by_id)
            if changed:
                super(ResPartner, changed).write({'ikiku_mobile_set_by_id': False})
        return super().write(vals)
