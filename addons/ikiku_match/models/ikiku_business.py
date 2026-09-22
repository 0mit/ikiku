# Part of iKiKu. Licensed under AGPL-3.0.
"""Where a business is, for databases made before it had a place of its own.

Until 2026-09-16 a business's province and city were its holder's. Here, where both
the business and the worker record are known, a café that only ever had its holder's
place learns one from its own needs.
"""
from odoo import api, models

from .ikiku_demand import OPEN_STATES

FILLED = ("جای این کسب‌وکار از آخرین اعلامِ نیاز برداشته شد، چون تا این به‌روزرسانی جای جدایی "
          "نداشت. اگر درست نیست، همین‌جا عوض کنید.")
DETACHED = ("جای این کسب‌وکار تا این به‌روزرسانی همان جای زندگیِ دارنده بود؛ از آخرین اعلامِ نیاز "
            "برداشته شد. اگر درست نیست، همین‌جا عوض کنید.")


class IkikuBusiness(models.Model):
    _inherit = 'ikiku.business'

    @api.model
    def _ikiku_place_from_needs(self):
        """Returns (filled, detached) counts. A holder with no worker record keeps the place
        they had: for them the old place was the café's, and staff may have typed it."""
        Demand = self.env['ikiku.demand']
        Resource = self.env['ikiku.resource']
        filled = detached = 0
        for business in self.with_context(active_test=False).search([]):
            last = Demand.search([('business_id', '=', business.id)], order='create_date desc, id desc', limit=1)
            if not last:
                continue
            if not business.place_id:
                business.write({'place_id': last.place_id.id})
                business.message_post(body=FILLED)
                filled += 1
                continue
            holder = business.partner_id
            is_worker = Resource.search_count([('partner_id.commercial_partner_id', '=', holder.id)], limit=1)
            at_home = business.place_id and business.place_id == holder.place_id
            elsewhere = last.place_id != business.place_id
            if is_worker and at_home and elsewhere:
                business.write({'place_id': last.place_id.id})
                business.message_post(body=DETACHED)
                detached += 1
        return filled, detached


MOVED_WITH = ("جای کسب‌وکار از «%s» به «%s» عوض شد و این نیاز، که همان‌جا بود، با آن رفت؛ "
              "پیشنهادها دوباره ساخته شدند. اگر کار جای دیگری است، جای نیاز را همین‌جا عوض کنید.")
STAYED = ("جای کسب‌وکار به «%s» عوض شد؛ این نیاز در «%s» ماند، چون جایش با جای کسب‌وکار یکی نبود. "
          "اگر باید با کسب‌وکار می‌رفت، جایش را همین‌جا عوض کنید.")
BOOKED = ("جای کسب‌وکار به «%s» عوض شد؛ این نیاز قرارِ کارِ زنده دارد و عوض نشد. "
          "قرارِ کار عمومی است و تغییرش با همکارانِ ایکیکوست.")


class IkikuBusinessPlaceFollow(models.Model):
    """When a café moves, the open needs that were AT the café move with it.

    A need has a place of its own (the work can be elsewhere), so only the needs whose place
    was the café's old place follow; a need placed elsewhere stays, and is told. A need with a
    live booking is not touched (بند ۷) and is told too. Decided by the operator on 2026-09-22,
    after a café's place was refined in the back office and its need stayed at the city.
    """
    _inherit = 'ikiku.business'

    def write(self, vals):
        moving = 'place_id' in vals or 'place_hint' in vals
        before = {b.id: (b.place_id, b.place_hint) for b in self} if moving else {}
        result = super().write(vals)
        if moving:
            self._ikiku_place_follow(before)
        return result

    def _ikiku_place_follow(self, before):
        Demand = self.env['ikiku.demand'].sudo()
        for business in self:
            old_place, old_hint = before.get(business.id, (False, ''))
            new_place, new_hint = business.place_id, business.place_hint
            if new_place == old_place and (new_hint or '') == (old_hint or ''):
                continue
            needs = Demand.search([('business_id', '=', business.id), ('state', 'in', OPEN_STATES)])
            for need in needs:
                if need.ikiku_live_bookings():
                    need.message_post(body=BOOKED % new_place.display_name)
                    continue
                if need.place_id != old_place:
                    need.message_post(body=STAYED % (new_place.display_name, need.place_id.display_name))
                    continue
                vals = {}
                if new_place != old_place:
                    vals['place_id'] = new_place.id
                if (new_hint or '') != (old_hint or ''):
                    vals['place_hint'] = new_hint or False
                if 'place_id' in vals:
                    # The same path a change from the café's own page takes: proposals rebuilt.
                    need.ikiku_apply_change({'place_id': vals['place_id']})
                    if 'place_hint' in vals:
                        need.write({'place_hint': vals['place_hint']})
                else:
                    need.write(vals)
                need.message_post(body=MOVED_WITH % (old_place.display_name if old_place else "—",
                                                     new_place.display_name))
