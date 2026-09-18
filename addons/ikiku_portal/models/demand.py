# Part of iKiKu. Licensed under AGPL-3.0.
from odoo import api, models

from odoo.addons.ikiku_base.models.jalali import to_fa_digits

OPEN_STATES = ('open', 'proposed')
# Skill chips on an open-job card (2026-09-17): the need's own required skills first, then the
# role's core skills from the standard, at most this many; the rest are on the role's page.
CARD_SKILLS = 4
ROLE_SHORTCUTS = ('spec_dishwashing', 'spec_barista', 'spec_line_cook', 'spec_waiter')

# What an open-job card can show, each tied to the field whose visibility row decides
# it. A value whose field is not public (or has no row) is left out: fail closed.
PUBLIC_DISPLAY = [
    ('seats', 'seats', lambda d: to_fa_digits(d.seats)),
    ('work_type', 'work_type_id', lambda d: d.work_type_id.name or ''),
    ('province', 'province_id', lambda d: d.province_id.name or ''),
    ('city', 'city', lambda d: d.city or ''),
    # Where the work is, as fine as this record may say it: place_public_id is the
    # neighbourhood of a need whose place is a street (place.located decides, not this line).
    ('place', 'place_public_id', lambda d: d.place_public_id.path or ''),
    # The business's name, only when its holder chose to show it (public_name is empty otherwise).
    ('business', 'business_public_name', lambda d: d.business_public_name or ''),
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
        hidden = set(self.env['ikiku.spec.node'].sudo().ikiku_hidden_ids())
        for demand in self.sudo().search(domain, order='date_start, id', limit=limit):
            node = demand.position_id.spec_node_id
            values = {'position': node.name or ''}
            # The standard is public: the role and its skills link into /roles and /skills, the
            # knowledge base. Nothing here reaches the business.
            if node.kind == 'role' and node.id not in hidden:
                values['position_url'] = '/roles/%s' % node.code
                skills = demand.position_id.required_node_ids.filtered(lambda n: n.kind == 'competency')
                skills |= node.requirement_ids.filtered(lambda r: r.importance == 'core').mapped('skill_id')
                skills = skills.filtered(lambda n: n.id not in hidden)
                values['skills'] = [(s.plain_label or s.name, '/skills/%s' % s.code) for s in skills[:CARD_SKILLS]]
                values['more_skills'] = len(node.requirement_ids) > len(values['skills'])
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
