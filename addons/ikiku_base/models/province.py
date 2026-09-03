# Part of iKiKu. Licensed under AGPL-3.0.
from odoo import api, fields, models


class IkikuProvince(models.Model):
    _name = 'ikiku.province'
    _description = "استان"
    _order = 'name'

    name = fields.Char("نام استان", required=True, translate=False)
    code = fields.Char("کد", required=True, size=8)
    centre = fields.Char("مرکز استان")
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint('UNIQUE(code)', "کد استان باید یکتا باشد.")

    @api.depends('name', 'centre')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = rec.name
