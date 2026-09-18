# Part of iKiKu. Licensed under AGPL-3.0.
"""A person waiting for a café that is not hiring now (operator, 2026-09-18).

A person picks cafés they would like to work for that have no open need today, and joins each
one's queue. The queue is kept IN ORDER, and the order is recorded, not worked out: `sequence`
is the number a person drew when they joined -- one more than anybody before them at that
café, and never given to anybody else, even after they leave. «نفرِ سوم» is a fact about who
came when.

What the queue is not: a ranking. When the café opens a need, proposals are still built and
ranked by the published formula (بند ۸) and nothing here adds to a score. The queue tells the
person that the café is hiring again and tells the café who has been waiting for it, in the
order they came.

Joining is consent to be seen: a person in a café's queue is listed to that café, and to no
one else.
"""
from odoo import api, fields, models
from odoo.exceptions import UserError


class IkikuFavorite(models.Model):
    _name = 'ikiku.favorite'
    _description = "صفِ انتظارِ یک کافه"
    _order = 'business_id, sequence'

    partner_id = fields.Many2one('res.partner', string="شخص", required=True, index=True, ondelete='cascade')
    business_id = fields.Many2one('ikiku.business', string="کسب‌وکار", required=True, index=True,
                                  ondelete='cascade')
    sequence = fields.Integer("نوبت", required=True, readonly=True,
                              help="شماره‌ای که هنگامِ پیوستن گرفت؛ یکی بیشتر از همهٔ پیشینیان، و به کسِ دیگری داده نمی‌شود.")
    joined_on = fields.Datetime("پیوست", required=True, readonly=True, default=fields.Datetime.now)
    active = fields.Boolean(default=True)
    left_on = fields.Datetime("بیرون رفت", readonly=True)
    position = fields.Integer("جای کنونی در صف", compute='_compute_position',
                              help="چند نفرِ هنوز منتظر پیش از او پیوسته‌اند، به‌علاوهٔ یک.")

    _once = models.Constraint('UNIQUE(partner_id, business_id, sequence)', "یک نوبت یک بار.")

    def _compute_position(self):
        for entry in self:
            entry.position = self.search_count([('business_id', '=', entry.business_id.id),
                                                ('sequence', '<', entry.sequence)]) + 1 if entry.active else 0

    @api.model
    def ikiku_join(self, partner, business):
        """Join `business`'s queue, or return the place already held. The number is drawn under a
        lock on the café's row, so two people joining at once never draw the same one."""
        mine = self.sudo().search([('partner_id', '=', partner.id), ('business_id', '=', business.id)], limit=1)
        if mine:
            return mine
        if business.partner_id.commercial_partner_id == partner.commercial_partner_id:
            raise UserError("صفِ کافهٔ خودتون نمی‌شه.")
        self.env.cr.execute("SELECT id FROM ikiku_business WHERE id = %s FOR UPDATE", (business.id,))
        self.env.cr.execute("SELECT COALESCE(MAX(sequence), 0) FROM ikiku_favorite WHERE business_id = %s",
                            (business.id,))
        drawn = self.env.cr.fetchone()[0] + 1
        return self.sudo().create({'partner_id': partner.id, 'business_id': business.id, 'sequence': drawn})

    def ikiku_leave(self):
        """Leave the queue. The number is not reused: whoever joins next draws a new one."""
        self.sudo().write({'active': False, 'left_on': fields.Datetime.now()})
        return True
