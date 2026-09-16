# Part of iKiKu. Licensed under AGPL-3.0.
"""Changing and closing a need, where the proposals and bookings made for it are known.

- A need with a live booking is not changed or closed here: a booking is public, a
  commitment cannot be quietly withdrawn (بند ۷), and staff finalise bookings (D-16 A).
- A change drops the proposals nobody accepted and ranks again, because other dates, a
  different place or kind of work make the old ranking wrong. The change itself is
  tracked on the need.
- Filled and cancelled are different ends (operator, 2026-09-16); a cancellation needs a
  written reason.
"""
from odoo import fields, models
from odoo.exceptions import UserError

LIVE_BOOKING_STATES = ('confirmed', 'at_risk', 'in_progress')
OPEN_STATES = ('open', 'proposed')
CHANGEABLE = ('position_id', 'work_type_id', 'seats', 'date_start', 'date_end', 'province_id', 'city')


class IkikuDemand(models.Model):
    _inherit = 'ikiku.demand'

    def ikiku_live_bookings(self):
        return self.env['ikiku.booking'].sudo().search([
            ('demand_id', 'in', self.ids), ('state', 'in', LIVE_BOOKING_STATES)])

    def _ikiku_check_closable(self):
        for rec in self:
            if rec.state not in OPEN_STATES:
                raise UserError("این نیاز دیگر باز نیست.")
            if rec.ikiku_live_bookings():
                raise UserError("برای این نیاز قرارِ کار بسته شده؛ عوض کردن یا لغوش با همکارانِ ایکیکوست، "
                                "چون قرارِ کار عمومی است.")

    def _ikiku_drop_proposals(self):
        proposals = self.env['ikiku.proposal'].sudo().search([('demand_id', 'in', self.ids),
                                                              ('state', '=', 'proposed')])
        count = len(proposals)
        proposals.unlink()
        return count

    def ikiku_apply_change(self, vals):
        """Change an open need from its business's page. Returns the proposals made again."""
        self.ensure_one()
        self._ikiku_check_closable()
        vals = {key: value for key, value in vals.items() if key in CHANGEABLE}
        changed = {key: value for key, value in vals.items()
                   if (self[key].id if hasattr(self[key], 'id') else self[key]) != value}
        if not changed:
            return self.env['ikiku.proposal']
        self.write(changed)
        dropped = self._ikiku_drop_proposals()
        self.state = 'open'
        made = self.env['ikiku.proposal'].sudo().build_for_demand(self)
        self.message_post(body="درخواست به دستِ %s عوض شد. %d پیشنهادِ قبلی برداشته شد و %d پیشنهاد "
                               "دوباره ساخته شد." % (self.env.user.name, dropped, len(made)))
        return made

    def _ikiku_close(self, state, vals=None):
        self._ikiku_check_closable()
        for rec in self:
            proposals = self.env['ikiku.proposal'].sudo().search([('demand_id', '=', rec.id),
                                                                  ('state', '=', 'proposed')])
            proposals.write({'state': 'expired'})
            rec.write(dict(vals or {}, state=state, closed_on=fields.Datetime.now(),
                           closed_by_id=self.env.user.id))

    def ikiku_mark_filled(self):
        """The business found the people it needed."""
        self._ikiku_close('filled')
        for rec in self:
            rec.message_post(body="%s نوشت نیرو پیدا شد و درخواست بسته شد." % self.env.user.name)
        return True

    def ikiku_cancel(self, reason):
        """Cancel with a written reason, or not at all."""
        reason = (reason or '').strip()
        if not reason:
            raise UserError("دلیلِ لغو را بنویسید؛ بدونِ دلیل لغو نمی‌شود.")
        self._ikiku_close('cancelled', {'cancel_reason': reason})
        for rec in self:
            rec.message_post(body="%s درخواست را لغو کرد." % self.env.user.name)
        return True

    def action_ikiku_mark_filled(self):
        return self.ikiku_mark_filled()
