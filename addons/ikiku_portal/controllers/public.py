# Part of iKiKu. Licensed under AGPL-3.0.
"""The open web.

Everything here is served through `ikiku_public_values()`, which reads the
visibility policy table -- so what the public sees is decided by DATA a person
can audit, not by what a template happens to print. A field nobody classified
is restricted and therefore absent: fail closed.
"""
from odoo import http
from odoo.http import request

from odoo.addons.ikiku_base.models.jalali import to_latin_digits

# How a claim reads next to a person's name, in spoken words (D-9, D-10). The model's
# selections stay as they are for staff; a key missing here falls back to them.
CLAIM_METHODS = {
    'self': "خودش",
    'coworker': "کسی که باهاش کار کرده",
    'employer': "جایی که کار کرده",
    'academy': "آموزشگاه",
    'platform': "ایکیکو",
    'document': "مدرک",
}
CLAIM_STATES = {
    'claimed': "خودش گفته",
    'supported': "تأیید شده",
    'contested': "کسی قبول نداره",
    'withdrawn': "پس گرفته شد",
}


class IkikuPublic(http.Controller):

    @http.route('/p/<string:slug>', type='http', auth='public', website=True)
    def public_profile(self, slug, **kw):
        resource = request.env['ikiku.resource'].sudo().search(
            [('slug', '=', slug), ('state', 'in', ('active', 'paused'))], limit=1)
        if not resource:
            return request.not_found()
        # The professional record, and only that.
        assertions = resource.assertion_ids.filtered(lambda a: a.state in ('supported', 'contested'))
        bookings = request.env['ikiku.booking'].sudo().search([
            ('resource_id', '=', resource.id),
            ('state', 'in', ('confirmed', 'in_progress', 'done', 'cancelled')),
        ])
        return request.render('ikiku_portal.public_profile', {
            'resource': resource,
            'values': resource.ikiku_public_values('public'),
            'assertions': assertions,
            'claim_methods': CLAIM_METHODS,
            'claim_states': CLAIM_STATES,
            'bookings': [b.public_payload() for b in bookings],
        })

    @http.route('/jobs', type='http', auth='public', website=True)
    def public_jobs(self, province=None, **kw):
        province = to_latin_digits(province or '').strip()
        province_id = int(province) if province.isascii() and province.isdigit() else None
        return request.render('ikiku_portal.public_jobs', {
            'jobs': request.env['ikiku.demand'].ikiku_public_open(province_id=province_id),
            'provinces': request.env['place.node'].sudo().search([('kind', '=', 'province')]),
            'province_id': province_id,
        })

    @http.route('/bookings', type='http', auth='public', website=True)
    def public_bookings(self, **kw):
        """The public register of commitments.

        بند ۷ ratified: the commitment is published, the venue is withheld until
        work begins. A cancellation appears here the moment it happens -- which
        is the entire enforcement mechanism.
        """
        bookings = request.env['ikiku.booking'].sudo().search([], order='published_on desc',
                                                              limit=200)
        return request.render('ikiku_portal.public_bookings', {
            'bookings': [b.public_payload() for b in bookings]})

    @http.route('/costs', type='http', auth='public', website=True)
    def public_costs(self, **kw):
        periods = request.env['ikiku.cost.period'].sudo().search(
            [('is_public', '=', True), ('state', '!=', 'draft')], order='date_start desc')
        return request.render('ikiku_portal.public_costs', {'periods': periods})
