# Part of iKiKu. Licensed under AGPL-3.0.
from odoo import api, models

from odoo.addons.ikiku_base.models.jalali import to_fa_digits

OPEN_STATES = ('open', 'proposed')


class IkikuDemand(models.Model):
    _inherit = 'ikiku.demand'

    @api.model
    def ikiku_public_open(self, limit=None, province_id=None):
        """Open needs as the public sees them: the standard position, the province,
        the dates and the seats — and nothing else.

        Returned as plain values rather than records, so a template can never reach
        the business behind a need; the venue stays private here, as it does on the
        register of commitments until work begins. Public on purpose (a QWeb page
        calls it), and it returns only what /ikiku/jobs has always published."""
        domain = [('state', 'in', OPEN_STATES)]
        if province_id:
            domain.append(('province_id', '=', province_id))
        demands = self.sudo().search(domain, order='date_start, id', limit=limit)
        return [{
            'position': demand.position_id.spec_node_id.name or '',
            'province': demand.province_id.name or '',
            'date_start_fa': demand.date_start_fa,
            'date_end_fa': demand.date_end_fa,
            'seats': to_fa_digits(demand.seats),
        } for demand in demands]

    @api.model
    def ikiku_public_open_count(self):
        return self.sudo().search_count([('state', 'in', OPEN_STATES)])

    @api.model
    def ikiku_fa_digits(self, value):
        """For a page: the dates already come in Persian digits, so counts do too."""
        return to_fa_digits(value)
