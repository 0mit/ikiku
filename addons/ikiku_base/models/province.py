# Part of iKiKu. Licensed under AGPL-3.0.
from odoo import api, fields, models

# Tehran first, as the operator asked; then Persian alphabetical order, which the
# data file already follows. The database cannot produce that order from the
# names: it sorts گ, ک, پ and چ by code point, after the Arabic letters, so
# گیلان would land after مازندران.
PROVINCE_ORDER = (
    'TE', 'EA', 'WA', 'AR', 'IS', 'AL', 'IL', 'BU', 'CB', 'SK', 'RK', 'NK', 'KZ', 'ZA', 'SE', 'SB',
    'FA', 'QA', 'QO', 'KD', 'KE', 'KS', 'KB', 'GO', 'GI', 'LO', 'MZ', 'MR', 'HO', 'HA', 'YA',
)


class IkikuProvince(models.Model):
    _name = 'ikiku.province'
    _description = "استان"
    _order = 'sequence, name'

    sequence = fields.Integer("ترتیب", default=100)
    name = fields.Char("نام استان", required=True, translate=False)
    code = fields.Char("کد", required=True, size=8)
    centre = fields.Char("مرکز استان")
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint('UNIQUE(code)', "کد استان باید یکتا باشد.")

    @api.depends('name', 'centre')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = rec.name

    @api.model
    def _ikiku_apply_order(self):
        """Write PROVINCE_ORDER into `sequence`. Run once on install, from the
        noupdate province data, and once by the 19.0.0.1.1 migration -- never on
        every update, so an order staff set afterwards is left alone."""
        Province = self.with_context(active_test=False)
        for position, code in enumerate(PROVINCE_ORDER, start=1):
            Province.search([('code', '=', code)]).sequence = position
        return True
