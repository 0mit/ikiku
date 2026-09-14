# Part of iKiKu. Licensed under AGPL-3.0.
"""Hint and steer, one question per screen.

Three rules, applied on both sides of the portal:
  1. Never a bare free-text field. Free text is always followed by a resolution
     step where the system PROPOSES standard nodes and the person confirms.
  2. The remainder is kept. Whatever does not resolve is written to
     ikiku.spec.candidate verbatim, never dropped to make a form validate.
  3. Six screens maximum. These users are on phones, often mid-shift.
"""
from urllib.parse import urlencode

from odoo import http
from odoo.exceptions import ValidationError
from odoo.http import request

from odoo.addons.ikiku_base.models.jalali import jalali_to_gregorian
from odoo.addons.ikiku_portal.models.mobile_challenge import MESSAGES


def _mask(mobile):
    return mobile[:6] + '***' + mobile[-4:] if mobile and len(mobile) > 10 else mobile


def _parse_jalali(value):
    """Portal input is Jalali; storage is Gregorian. Convert at the boundary."""
    if not value:
        return False
    parts = value.replace('-', '/').split('/')
    if len(parts) != 3:
        return False
    try:
        jy, jm, jd = (int(p) for p in parts)
        gy, gm, gd = jalali_to_gregorian(jy, jm, jd)
        return '%04d-%02d-%02d' % (gy, gm, gd)
    except (ValueError, IndexError):
        return False


class IkikuPortal(http.Controller):

    # ------------------------------------------------------------- resources
    @http.route('/ikiku/join', type='http', auth='user', website=True, sitemap=False)
    def join(self, **kw):
        partner = request.env.user.partner_id
        resource = request.env['ikiku.resource'].sudo().search(
            [('partner_id', '=', partner.id)], limit=1)
        return request.render('ikiku_portal.resource_intake', {
            'resource': resource,
            'partner': partner,
            'provinces': request.env['ikiku.province'].sudo().search([]),
            'step': kw.get('step', '1'),
            'error': MESSAGES.get(kw.get('error')),
            'otp_enabled': request.env['ikiku.mobile.challenge'].sudo()._enabled(),
            'mobile_verified': bool(partner.sudo().ikiku_mobile_verified_on),
        })

    @http.route('/ikiku/join/submit', type='http', auth='user', methods=['POST'],
                website=True, csrf=True)
    def join_submit(self, **post):
        partner = request.env.user.partner_id
        partner_sudo = partner.sudo()
        Resource = request.env['ikiku.resource'].sudo()
        try:
            mobile = partner.normalise_mobile(post.get('mobile'))
        except ValidationError:
            return request.redirect('/ikiku/join?' + urlencode({'error': 'mobile'}))
        partner_sudo.write({
            'ikiku_province_id': int(post['province_id']) if post.get('province_id') else False,
            'ikiku_city': post.get('city'),
        })
        resource = Resource.search([('partner_id', '=', partner.id)], limit=1)
        vals = {'headline': post.get('headline'), 'bio': post.get('bio')}
        if resource:
            resource.write(vals)
        else:
            vals['partner_id'] = partner.id
            resource = Resource.create(vals)
        request.env.user.sudo().group_ids = [
            (4, request.env.ref('ikiku_base.group_ikiku_resource').id)]
        if mobile and not (mobile == partner_sudo.ikiku_mobile and partner_sudo.ikiku_mobile_verified_on):
            Challenge = request.env['ikiku.mobile.challenge'].sudo()
            if Challenge._enabled():
                # The number becomes the anchor only once its owner types the code.
                _challenge, error = Challenge.start(partner, mobile)
                if error:
                    return request.redirect('/ikiku/join?' + urlencode({'error': error}))
                return request.redirect('/ikiku/join/verify')
            # Without SMS the number is written as typed and stays unproven, as before.
            if request.env['res.partner'].sudo().with_context(active_test=False).search_count(
                    [('ikiku_mobile', '=', mobile), ('id', '!=', partner.id)], limit=1):
                return request.redirect('/ikiku/join?' + urlencode({'error': 'held'}))
            partner_sudo.ikiku_mobile = mobile
        return request.redirect('/ikiku/join/skills')

    @http.route('/ikiku/join/verify', type='http', auth='user', website=True, sitemap=False)
    def join_verify(self, **kw):
        challenge = request.env['ikiku.mobile.challenge'].sudo()._latest(request.env.user.partner_id)
        if not challenge:
            return request.redirect('/ikiku/join')
        return request.render('ikiku_portal.resource_verify', {
            'challenge': challenge,
            'status': challenge._payload(),
            'masked': _mask(challenge.mobile),
            'error': MESSAGES.get(kw.get('error')),
        })

    @http.route('/ikiku/join/verify/state', type='http', auth='user', methods=['GET'], sitemap=False)
    def join_verify_state(self, **kw):
        challenge = request.env['ikiku.mobile.challenge'].sudo()._latest(request.env.user.partner_id)
        return request.make_json_response(challenge._payload() if challenge else {'state': 'none'})

    @http.route('/ikiku/join/verify/submit', type='http', auth='user', methods=['POST'],
                website=True, csrf=True)
    def join_verify_submit(self, code=None, **post):
        challenge = request.env['ikiku.mobile.challenge'].sudo()._latest(request.env.user.partner_id)
        if not challenge:
            return request.redirect('/ikiku/join')
        error = challenge.check(code)
        if error:
            return request.redirect('/ikiku/join/verify?' + urlencode({'error': error}))
        return request.redirect('/ikiku/join/skills')

    @http.route('/ikiku/join/verify/resend', type='http', auth='user', methods=['POST'],
                website=True, csrf=True)
    def join_verify_resend(self, **post):
        Challenge = request.env['ikiku.mobile.challenge'].sudo()
        partner = request.env.user.partner_id
        latest = Challenge._latest(partner)
        if not latest or not Challenge._enabled():
            return request.redirect('/ikiku/join')
        _challenge, error = Challenge.start(partner, latest.mobile)
        return request.redirect('/ikiku/join/verify' + ('?' + urlencode({'error': error}) if error else ''))

    @http.route('/ikiku/join/skills', type='http', auth='user', website=True, sitemap=False)
    def join_skills(self, **kw):
        partner = request.env.user.partner_id
        resource = request.env['ikiku.resource'].sudo().search(
            [('partner_id', '=', partner.id)], limit=1)
        raw = kw.get('raw', '')
        proposals = request.env['ikiku.spec.node'].sudo().resolve_text(raw) if raw \
            else request.env['ikiku.spec.node'].sudo().browse()
        return request.render('ikiku_portal.resource_skills', {
            'resource': resource, 'raw': raw, 'proposals': proposals,
            'families': request.env['ikiku.spec.node'].sudo().search(
                [('kind', '=', 'competency')]),
        })

    @http.route('/ikiku/join/skills/confirm', type='http', auth='user', methods=['POST'],
                website=True, csrf=True)
    def join_skills_confirm(self, **post):
        partner = request.env.user.partner_id
        resource = request.env['ikiku.resource'].sudo().search(
            [('partner_id', '=', partner.id)], limit=1)
        raw = (post.get('raw') or '').strip()
        node_id = int(post['node_id']) if post.get('node_id') else False
        if node_id:
            node = request.env['ikiku.spec.node'].sudo().browse(node_id)
            resource.sudo().claim_skill(node)
            # Rule 2: if the tree did not propose what they picked, the words
            # they used are new information about how people actually speak.
            proposed = request.env['ikiku.spec.node'].sudo().resolve_text(raw)
            if raw and node not in proposed:
                request.env['ikiku.spec.candidate'].sudo().record(
                    raw, partner=partner, source='ikiku.resource', res_id=resource.id)
        elif raw:
            # Nothing matched at all. Keep it anyway -- this is exactly the
            # signal the standard needs in order to grow.
            request.env['ikiku.spec.candidate'].sudo().record(
                raw, partner=partner, source='ikiku.resource', res_id=resource.id)
        return request.redirect('/ikiku/join/availability')

    @http.route('/ikiku/join/availability', type='http', auth='user', website=True,
                sitemap=False)
    def join_availability(self, **kw):
        partner = request.env.user.partner_id
        resource = request.env['ikiku.resource'].sudo().search(
            [('partner_id', '=', partner.id)], limit=1)
        return request.render('ikiku_portal.resource_availability', {
            'resource': resource,
            'provinces': request.env['ikiku.province'].sudo().search([]),
        })

    @http.route('/ikiku/join/availability/save', type='http', auth='user', methods=['POST'],
                website=True, csrf=True)
    def join_availability_save(self, **post):
        partner = request.env.user.partner_id
        resource = request.env['ikiku.resource'].sudo().search(
            [('partner_id', '=', partner.id)], limit=1)
        start, end = _parse_jalali(post.get('date_start')), _parse_jalali(post.get('date_end'))
        if start and end:
            request.env['ikiku.availability'].sudo().create({
                'resource_id': resource.id,
                'date_start': start, 'date_end': end,
                'province_id': int(post['province_id']),
                'city': post.get('city'),
                'can_relocate': bool(post.get('can_relocate')),
                'hours_per_week': int(post.get('hours_per_week') or 40),
            })
        if resource.state == 'draft' and resource.skill_ids or resource.assertion_ids:
            resource.sudo().state = 'submitted'
        return request.redirect('/ikiku/me')

    @http.route('/ikiku/me', type='http', auth='user', website=True, sitemap=False)
    def me(self, **kw):
        partner = request.env.user.partner_id
        resource = request.env['ikiku.resource'].sudo().search(
            [('partner_id', '=', partner.id)], limit=1)
        bookings = request.env['ikiku.booking'].sudo().search(
            [('resource_id', '=', resource.id)]) if resource else []
        return request.render('ikiku_portal.resource_home', {
            'resource': resource, 'bookings': bookings})

    # ------------------------------------------------------------ businesses
    def _business(self):
        partner = request.env.user.partner_id.commercial_partner_id
        return request.env['ikiku.business'].sudo().search([('partner_id', '=', partner.id)], limit=1)

    @http.route('/ikiku/business/name', type='http', auth='user', website=True, sitemap=False)
    def business_name(self, **kw):
        """The first question of کو؟, and the way to change the answer later."""
        return request.render('ikiku_portal.business_name', {
            'business': self._business(), 'error': kw.get('error')})

    @http.route('/ikiku/business/name/save', type='http', auth='user', methods=['POST'],
                website=True, csrf=True)
    def business_name_save(self, **post):
        name = ' '.join((post.get('name') or '').split())
        if not name:
            return request.redirect('/ikiku/business/name?error=1')
        business = self._business()
        if business:
            business.name = name
            return request.redirect('/ikiku/business')
        request.env['ikiku.business'].sudo().create({
            'partner_id': request.env.user.partner_id.commercial_partner_id.id,
            'name': name,
        })
        request.env.user.sudo().group_ids = [
            (4, request.env.ref('ikiku_base.group_ikiku_business').id)]
        return request.redirect('/ikiku/business/position/new')

    @http.route('/ikiku/business/position/new', type='http', auth='user', website=True,
                sitemap=False)
    def position_new(self, **kw):
        if not self._business():
            return request.redirect('/ikiku/business/name')
        raw = kw.get('raw', '')
        proposals = request.env['ikiku.spec.node'].sudo().resolve_text(raw) if raw \
            else request.env['ikiku.spec.node'].sudo().browse()
        return request.render('ikiku_portal.business_position', {
            'raw': raw, 'proposals': proposals,
            'all_nodes': request.env['ikiku.spec.node'].sudo().search(
                [('kind', 'in', ('competency', 'family'))]),
        })

    @http.route('/ikiku/business/position/save', type='http', auth='user', methods=['POST'],
                website=True, csrf=True)
    def position_save(self, **post):
        business = self._business()
        if not business:
            return request.redirect('/ikiku/business/name')
        node = request.env['ikiku.spec.node'].sudo().browse(int(post['node_id']))
        request.env['ikiku.position'].sudo().steer(
            business, post.get('raw') or node.name, chosen_node=node)
        return request.redirect('/ikiku/business')

    @http.route('/ikiku/business', type='http', auth='user', website=True, sitemap=False)
    def business_home(self, **kw):
        partner = request.env.user.partner_id.commercial_partner_id
        business = request.env['ikiku.business'].sudo().search(
            [('partner_id', '=', partner.id)], limit=1)
        demands = request.env['ikiku.demand'].sudo().search(
            [('business_id', '=', business.id)]) if business else []
        return request.render('ikiku_portal.business_home', {
            'business': business, 'demands': demands,
            'provinces': request.env['ikiku.province'].sudo().search([]),
        })

    @http.route('/ikiku/business/demand/save', type='http', auth='user', methods=['POST'],
                website=True, csrf=True)
    def demand_save(self, **post):
        partner = request.env.user.partner_id.commercial_partner_id
        business = request.env['ikiku.business'].sudo().search(
            [('partner_id', '=', partner.id)], limit=1)
        start, end = _parse_jalali(post.get('date_start')), _parse_jalali(post.get('date_end'))
        if business and start and end:
            demand = request.env['ikiku.demand'].sudo().create({
                'business_id': business.id,
                'position_id': int(post['position_id']),
                'seats': int(post.get('seats') or 1),
                'date_start': start, 'date_end': end,
                'province_id': int(post['province_id']),
                'city': post.get('city'),
                'note': post.get('note'),
                'state': 'open',
            })
            request.env['ikiku.proposal'].sudo().build_for_demand(demand)
        return request.redirect('/ikiku/business')
