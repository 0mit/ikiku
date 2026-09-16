# Part of iKiKu. Licensed under AGPL-3.0.
from odoo import api, models

from odoo.addons.ikiku_base.models.jalali import to_fa_digits

OPEN_STATES = ('open', 'proposed')
ROLE_SHORTCUTS = ('spec_dishwashing', 'spec_barista', 'spec_line_cook', 'spec_waiter')

# What an open-job card can show, each tied to the field whose visibility row decides
# it. A value whose field is not public (or has no row) is left out: fail closed.
PUBLIC_DISPLAY = [
    ('seats', 'seats', lambda d: to_fa_digits(d.seats)),
    ('work_type', 'work_type_id', lambda d: d.work_type_id.name or ''),
    ('province', 'province_id', lambda d: d.province_id.name or ''),
    ('city', 'city', lambda d: d.city or ''),
    ('date_start_fa', 'date_start', lambda d: d.date_start_fa),
    ('date_end_fa', 'date_end', lambda d: d.date_end_fa),
]


class IkikuDemand(models.Model):
    _inherit = 'ikiku.demand'

    @api.model
    def ikiku_public_open(self, limit=None, province_id=None):
        """Open needs as the public sees them, as plain values rather than records, so a
        template can never reach the business behind a need.

        Which values appear is decided by the ikiku.demand rows of the visibility
        policy. The one hand-built value is the position: the public sees the standard
        name of the work, never the business's own title for it (that field is
        restricted), which is what /jobs has published from the start."""
        policy = {p.field_name: p.visibility for p in self.env['ikiku.visibility.policy'].sudo().search(
            [('model_name', '=', self._name)])}
        domain = [('state', 'in', OPEN_STATES)]
        if province_id:
            domain.append(('province_id', '=', province_id))
        out = []
        for demand in self.sudo().search(domain, order='date_start, id', limit=limit):
            values = {'position': demand.position_id.spec_node_id.name or ''}
            for key, field_name, getter in PUBLIC_DISPLAY:
                if policy.get(field_name) == 'public':
                    values[key] = getter(demand)
            out.append(values)
        return out

    @api.model
    def ikiku_public_open_count(self):
        return self.sudo().search_count([('state', 'in', OPEN_STATES)])

    @api.model
    def ikiku_role_shortcuts(self):
        """The home page's «همکار برای» links: four common skills as (id, everyday name).
        Plain values, read with sudo, because a visitor who is not signed in may not read
        the skill tree itself; the names are the public standard."""
        out = []
        for xmlid in ROLE_SHORTCUTS:
            node = self.env.ref('ikiku_base.%s' % xmlid, raise_if_not_found=False)
            if node:
                node = node.sudo()
                out.append((node.id, node.plain_label or node.name))
        return out

    @api.model
    def ikiku_fa_digits(self, value):
        """For a page: the dates already come in Persian digits, so counts do too."""
        return to_fa_digits(value)
