# Part of iKiKu. Licensed under AGPL-3.0.
"""Where a business is, for databases made before it had a place of its own.

Until 2026-09-16 a business's province and city were its holder's. Here, where both
the business and the worker record are known, a café that only ever had its holder's
place learns one from its own needs.
"""
from odoo import api, models

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
            if not business.province_id:
                business.write({'province_id': last.province_id.id, 'city': last.city})
                business.message_post(body=FILLED)
                filled += 1
                continue
            holder = business.partner_id
            is_worker = Resource.search_count([('partner_id.commercial_partner_id', '=', holder.id)], limit=1)
            at_home = (business.province_id == holder.ikiku_province_id
                       and (business.city or '') == (holder.ikiku_city or ''))
            elsewhere = (last.province_id != business.province_id
                         or (last.city or '') != (business.city or ''))
            if is_worker and at_home and elsewhere:
                business.write({'province_id': last.province_id.id, 'city': last.city})
                business.message_post(body=DETACHED)
                detached += 1
        return filled, detached
