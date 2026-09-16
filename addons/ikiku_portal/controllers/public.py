# Part of iKiKu. Licensed under AGPL-3.0.
"""The open web.

Everything here is served through `ikiku_public_values()`, which reads the
visibility policy table -- so what the public sees is decided by DATA a person
can audit, not by what a template happens to print. A field nobody classified
is restricted and therefore absent: fail closed.
"""
from odoo import http
from odoo.http import request


class IkikuPublic(http.Controller):

    @http.route('/ikiku/p/<string:slug>', type='http', auth='public', website=True)
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
            'bookings': [b.public_payload() for b in bookings],
        })

    @http.route('/ikiku/jobs', type='http', auth='public', website=True)
    def public_jobs(self, province=None, **kw):
        province_id = int(province) if province and str(province).isdigit() else None
        return request.render('ikiku_portal.public_jobs', {
            'jobs': request.env['ikiku.demand'].ikiku_public_open(province_id=province_id),
            'provinces': request.env['ikiku.province'].sudo().search([]),
            'province_id': province_id,
        })

    @http.route('/ikiku/bookings', type='http', auth='public', website=True)
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

    @http.route('/ikiku/costs', type='http', auth='public', website=True)
    def public_costs(self, **kw):
        periods = request.env['ikiku.cost.period'].sudo().search(
            [('is_public', '=', True), ('state', '!=', 'draft')], order='date_start desc')
        return request.render('ikiku_portal.public_costs', {'periods': periods})
