# Part of iKiKu. Licensed under AGPL-3.0.
"""One question per screen, for workers (کی؟) and for businesses (کو؟).

Rules, applied on both sides:
  1. One question per screen, asked the way it would be asked out loud. Tap before
     type: skills, kinds of work, dates and counts are buttons.
  2. Free text is always followed by a resolution step where the system PROPOSES
     standard skills and the person confirms. Whatever does not resolve is kept in
     ikiku.spec.candidate verbatim, never dropped to make a form validate.
  3. Nothing fails silently. An error is shown next to its field on the same screen,
     with what was typed still there; a save goes on to the first unanswered step.
  4. At most six screens after signing in. These users are on phones, often mid-shift.

The worker screens double as edit screens: ?edit=1 comes back to /me.

One account may hold both sides (operator, 2026-09-16). The person's own place (استان و
شهر on /join/where) and a café's place are kept apart; either page offers the other side.
"""
from datetime import date

from werkzeug.exceptions import Forbidden

from odoo import http
from odoo.exceptions import UserError, ValidationError
from odoo.http import request

from odoo.addons.ikiku_base.models.jalali import to_fa_digits
from odoo.addons.ikiku_base.models.partner import STANDING_MAX, STANDING_PER_SUPPORTED, STANDING_VERIFIED
from odoo.addons.ikiku_portal.controllers.auth import ikiku_sides, remember_side
from odoo.addons.ikiku_portal.controllers.common import (
    DATE_ERRORS, date_widget, dates_text, dates_values, mask, parse_jalali, read_dates, tehran_today, to_int)
from odoo.addons.ikiku_portal.models.mobile_challenge import NEW_PARTNER_NAME

# Older imports keep working.
_int = to_int
_parse_jalali = parse_jalali

WORKER_STEPS = 5
BUSINESS_STEPS = 5
MAX_SEATS = 50


def _form_list(name):
    return [v for v in request.httprequest.form.getlist(name) if v]


class IkikuPortal(http.Controller):

    # ------------------------------------------------------------------ shared
    def _partner(self):
        return request.env.user.partner_id.sudo()

    def _competencies(self):
        """The signup tiles: every competency, grouped under its family, in the published
        order stored on the nodes (never popularity)."""
        Node = request.env['ikiku.spec.node'].sudo()
        groups = []
        for family in Node.search([('kind', '=', 'family'), ('parent_id', '!=', False)], order='sequence, id'):
            nodes = Node.search([('kind', '=', 'competency'), ('parent_id', '=', family.id)], order='sequence, id')
            if nodes:
                groups.append((family, nodes))
        return groups

    def _resolve(self, raw):
        if not raw:
            return request.env['ikiku.spec.node'].sudo().browse()
        return request.env['ikiku.spec.node'].sudo().resolve_text(raw).filtered(lambda n: n.kind == 'competency')

    def _city_suggestions(self):
        """What the city field suggests: every province's centre and the cities open jobs
        already name. Both are public; a city not on the list is still accepted."""
        cities = set(request.env['ikiku.province'].sudo().search([]).mapped('centre'))
        cities |= set(request.env['ikiku.demand'].sudo().search(
            [('state', 'in', ('open', 'proposed')), ('city', '!=', False)]).mapped('city'))
        return sorted(city for city in cities if city)

    def _needs_name(self, partner):
        return not (partner.name or '').strip() or partner.name == NEW_PARTNER_NAME

    def _staff_elsewhere(self):
        """A staff (internal) account has no worker page or café: it belongs in the backend."""
        return None if request.env.user.share else request.redirect('/odoo')

    def _number(self, partner):
        """The person's own number, masked, as their own pages show it."""
        return {
            'masked': mask(partner.ikiku_mobile),
            'proven': bool(partner.ikiku_mobile_verified_on),
            'can_prove': request.env['ikiku.mobile.challenge'].sudo()._enabled(),
        }

    def _availability_referenced(self, availability):
        return bool(availability) and bool(
            request.env['ikiku.proposal'].sudo().search_count([('availability_id', '=', availability.id)], limit=1)
            or request.env['ikiku.booking'].sudo().search_count([('availability_id', '=', availability.id)], limit=1))

    # ---------------------------------------------------------------- workers
    def _resource(self, create=False):
        Resource = request.env['ikiku.resource'].sudo()
        resource = Resource.search([('partner_id', '=', request.env.user.partner_id.id)], limit=1)
        if not resource and create:
            if not request.env.user.share:
                raise Forbidden()
            resource = self._partner()._ikiku_grant_role('ki')
        return resource

    def _availability(self, resource):
        return resource.availability_ids.filtered(lambda a: a.state == 'open').sorted(
            'date_start', reverse=True)[:1]

    def _skill_claims(self, resource):
        return resource.assertion_ids.filtered(lambda a: a.claim_kind == 'skill' and a.spec_node_id)

    def _worker_next(self, resource):
        partner = self._partner()
        if request.env['ikiku.mobile.challenge'].sudo()._enabled() and not partner.ikiku_mobile_verified_on:
            return '/enter'
        if self._needs_name(partner):
            return '/join/name'
        if not partner.ikiku_province_id:
            return '/join/where'
        if not self._skill_claims(resource):
            return '/join/skills'
        availability = self._availability(resource)
        if not availability:
            return '/join/when'
        if not availability.details_confirmed:
            return '/join/how'
        return '/me'

    def _after_worker_save(self, resource, edit):
        if resource.state == 'draft' and self._skill_claims(resource) and self._availability(resource):
            resource.state = 'submitted'
        return request.redirect('/me' if edit else self._worker_next(resource))

    def _worker_page(self, template, step, values):
        values.update({'step': step, 'total': WORKER_STEPS, 'edit': bool(values.get('edit'))})
        return request.render(template, values)

    @http.route('/join', type='http', auth='user', website=True, sitemap=False)
    def join(self, **kw):
        staff = self._staff_elsewhere()
        if staff:
            return staff
        return request.redirect(self._worker_next(self._resource(create=True)))

    @http.route('/join/name', type='http', auth='user', methods=['GET', 'POST'], website=True, sitemap=False)
    def join_name(self, edit=None, **post):
        """The person's own name. Business owners come here first too (for=ku)."""
        partner = self._partner()
        for_business = post.get('for') == 'ku'
        name = ' '.join((post.get('name') or '').split())
        if request.httprequest.method == 'POST':
            if name:
                partner.name = name
                if for_business:
                    return request.redirect('/business/name')
                return self._after_worker_save(self._resource(create=True), edit)
            error = "اسم رو ننوشتید. اینجا بنویسید."
        else:
            error = None
            name = '' if self._needs_name(partner) else partner.name
        return self._worker_page('ikiku_portal.join_name', 1, {
            'name': name, 'error': error, 'edit': edit, 'for_business': for_business})

    @http.route('/join/where', type='http', auth='user', methods=['GET', 'POST'], website=True, sitemap=False)
    def join_where(self, edit=None, **post):
        partner = self._partner()
        errors = {}
        province_id = to_int(post.get('province_id')) if request.httprequest.method == 'POST' \
            else partner.ikiku_province_id.id
        city = ' '.join((post.get('city') or '').split()) if request.httprequest.method == 'POST' \
            else (partner.ikiku_city or '')
        if request.httprequest.method == 'POST':
            province = request.env['ikiku.province'].sudo().browse(province_id or 0).exists()
            if not province:
                errors['province'] = "استان رو انتخاب نکردید."
            if not city:
                errors['city'] = "شهر رو ننوشتید."
            if not errors:
                partner.write({'ikiku_province_id': province.id, 'ikiku_city': city})
                resource = self._resource(create=True)
                availability = self._availability(resource)
                if availability and not self._availability_referenced(availability):
                    availability.write({'province_id': province.id, 'city': city})
                return self._after_worker_save(resource, edit)
        return self._worker_page('ikiku_portal.join_where', 2, {
            'provinces': request.env['ikiku.province'].sudo().search([]),
            'cities': self._city_suggestions(),
            'has_business': 'ku' in ikiku_sides(request.env.user),
            'province_id': province_id, 'city': city, 'errors': errors, 'edit': edit})

    @http.route('/join/skills', type='http', auth='user', methods=['GET', 'POST'], website=True, sitemap=False)
    def join_skills(self, edit=None, **post):
        resource = self._resource(create=True)
        partner = request.env.user.partner_id
        claimed = self._skill_claims(resource).mapped('spec_node_id')
        raw = (post.get('raw') or '').strip()
        error = None
        if request.httprequest.method == 'POST':
            Node = request.env['ikiku.spec.node'].sudo()
            chosen = Node.browse([to_int(v, 0) for v in _form_list('node_id')]).exists().filtered(
                lambda n: n.kind == 'competency')
            for node in chosen - claimed:
                resource.claim_skill(node)
            if raw:
                proposed = self._resolve(raw)
                if not chosen or not (chosen & proposed):
                    # Their own words are information about how people speak.
                    request.env['ikiku.spec.candidate'].sudo().record(
                        raw, partner=partner, source='ikiku.resource', res_id=resource.id)
            if chosen or claimed or raw:
                return self._after_worker_save(resource, edit)
            error = "حداقل یه کار رو بزنید، یا بنویسید چه کاری بلدید."
        return self._worker_page('ikiku_portal.join_skills', 3, {
            'groups': self._competencies(), 'claimed': claimed, 'raw': raw,
            'proposals': self._resolve(raw) if raw and request.httprequest.method == 'GET' else None,
            'error': error, 'edit': edit})

    @http.route('/join/when', type='http', auth='user', methods=['GET', 'POST'], website=True, sitemap=False)
    def join_when(self, edit=None, **post):
        resource = self._resource(create=True)
        partner = self._partner()
        error = None
        if request.httprequest.method == 'POST':
            start, end, error = read_dates(post)
            if not error:
                Availability = request.env['ikiku.availability'].sudo()
                current = self._availability(resource)
                referenced = self._availability_referenced(current)
                vals = {'date_start': start, 'date_end': end or False,
                        'province_id': partner.ikiku_province_id.id, 'city': partner.ikiku_city}
                try:
                    with request.env.cr.savepoint():
                        if current and not referenced:
                            current.write(vals)
                        else:
                            Availability.create(dict(vals, resource_id=resource.id))
                except ValidationError:
                    error = 'overlap'
                else:
                    return self._after_worker_save(resource, edit)
        values = dict(post) if request.httprequest.method == 'POST' else {}
        return self._worker_page('ikiku_portal.join_when', 4, {
            'dates': date_widget('worker', values), 'error': DATE_ERRORS.get(error), 'edit': edit})

    @http.route('/join/how', type='http', auth='user', methods=['GET', 'POST'], website=True, sitemap=False)
    def join_how(self, edit=None, **post):
        resource = self._resource(create=True)
        availability = self._availability(resource)
        if not availability:
            return request.redirect('/join/when')
        WorkType = request.env['ikiku.work.type'].sudo()
        shifts = request.env['ikiku.spec.node'].sudo().search(
            [('kind', '=', 'attribute'), ('code', 'in', ('shift-morning', 'shift-evening', 'shift-night'))],
            order='code')
        errors = {}
        if request.httprequest.method == 'POST':
            types = WorkType.browse([to_int(v, 0) for v in _form_list('work_type_id')]).exists()
            chosen_shifts = shifts.filtered(lambda s: str(s.id) in _form_list('shift_id'))
            relocate = post.get('relocate')
            if not types:
                errors['types'] = "یکی رو انتخاب کنید."
            if relocate not in ('yes', 'no'):
                errors['relocate'] = "آره یا نه رو بزنید."
            if not errors:
                availability.write({
                    'work_type_ids': [(6, 0, types.ids)],
                    'shift_node_ids': [(6, 0, chosen_shifts.ids)],
                    'can_relocate': relocate == 'yes',
                    'details_confirmed': True,
                })
                return self._after_worker_save(resource, edit)
            selected_types, selected_shifts = types, chosen_shifts
        else:
            selected_types, selected_shifts = availability.work_type_ids, availability.shift_node_ids
            relocate = ('yes' if availability.can_relocate else 'no') if availability.details_confirmed else None
        return self._worker_page('ikiku_portal.join_how', 5, {
            'work_types': WorkType.search([]), 'shifts': shifts,
            'selected_types': selected_types, 'selected_shifts': selected_shifts,
            'relocate': relocate, 'errors': errors, 'edit': edit})

    @http.route('/me', type='http', auth='user', website=True, sitemap=False)
    def me(self, **kw):
        resource = self._resource()
        if not resource:
            return request.redirect('/business' if self._businesses() else '/join')
        remember_side('ki')
        partner = self._partner()
        availability = self._availability(resource)
        next_step = self._worker_next(resource)
        supported = partner.ikiku_assertion_ids.filtered(lambda a: a.state == 'supported')
        bookings = request.env['ikiku.booking'].sudo().search([('resource_id', '=', resource.id)])
        return request.render('ikiku_portal.resource_home', {
            'resource': resource,
            'partner': partner,
            'next_step': next_step if next_step not in ('/me',) else False,
            'skills_text': '، '.join(n.plain_label or n.name for n in self._skill_claims(resource).mapped('spec_node_id')),
            'availability': availability,
            'dates_text': dates_text(availability.date_start, availability.date_end, tehran_today())
            if availability else '',
            'standing': to_fa_digits(('%.2f' % partner.ikiku_standing).rstrip('0').rstrip('.') or '0'),
            'standing_verified': to_fa_digits(('%g' % STANDING_VERIFIED)) if partner.ikiku_is_verified else False,
            'supported_count': to_fa_digits(len(supported)),
            'per_supported': to_fa_digits(('%g' % STANDING_PER_SUPPORTED).replace('.', '٫')),
            'standing_max': to_fa_digits('%g' % STANDING_MAX),
            'bookings': bookings,
            'first_visit': kw.get('saved') == '1',
            'sides': ikiku_sides(request.env.user),
            'number': self._number(partner),
        })

    # ------------------------------------------------------------- businesses
    def _businesses(self):
        """Every business the signed-in person holds (operator, 2026-09-16: one person may hold several)."""
        partner = request.env.user.partner_id.commercial_partner_id
        return request.env['ikiku.business'].sudo().search([('partner_id', '=', partner.id)], order='name, id')

    def _business(self, business_id=None):
        """One of the person's businesses: the one asked for, else the one the need being written
        is for, else the only one. Empty when it cannot be told which."""
        businesses = self._businesses()
        wanted = business_id or self._draft().get('business_id')
        if wanted:
            return businesses.filtered(lambda business: business.id == to_int(wanted, 0))
        return businesses if len(businesses) == 1 else businesses.browse()

    def _need_business(self):
        """(business, None) for the need being written, or (None, redirect) to name a business or
        to choose which one."""
        business = self._business()
        if business:
            return business, None
        if self._businesses():
            return None, request.redirect('/business/need/for')
        return None, request.redirect('/business/name')

    def _draft(self):
        return dict(request.session.get('ikiku_need') or {})

    def _keep_draft(self, draft):
        request.session['ikiku_need'] = draft

    def _business_page(self, template, step, values):
        business = self._business()
        values.update({'step': step, 'total': BUSINESS_STEPS, 'changing_need': bool(self._draft().get('edit_id')),
                       # Said only to a person with several businesses, so the need lands where they mean.
                       'for_business': business.name if business and len(self._businesses()) > 1 else False})
        return request.render(template, values)

    def _own_need(self, need_id):
        """A need of one of the person's businesses, or None."""
        demand = request.env['ikiku.demand'].sudo().browse(need_id).exists()
        return demand if demand and demand.business_id in self._businesses() else None

    def _need_missing(self, draft):
        for key, url in (('position_id', '/business/need/who'), ('work_type_id', '/business/need/type'),
                         ('seats', '/business/need/count'), ('date_start', '/business/need/when')):
            if not draft.get(key):
                return url
        return False

    @http.route('/business', type='http', auth='user', website=True, sitemap=False)
    def business_home(self, **kw):
        businesses = self._businesses()
        if not businesses:
            return request.redirect('/business/name')
        remember_side('ku')
        today = tehran_today()
        Demand = request.env['ikiku.demand'].sudo()
        return request.render('ikiku_portal.business_home', {
            'businesses': [{
                'business': business,
                'needs': [{'demand': d, 'seats': to_fa_digits(d.seats),
                           'dates': dates_text(d.date_start, d.date_end, today),
                           'is_open': d.state in ('open', 'proposed'),
                           'booked': bool(d.ikiku_live_bookings())}
                          for d in Demand.search([('business_id', '=', business.id)], order='create_date desc')],
            } for business in businesses],
            'note': {'filled': "درخواست بسته شد: نیرو پیدا کردید.",
                     'cancelled': "درخواست لغو شد. دلیلی که نوشتید ثبت شد.",
                     'changed': "تغییرها ثبت شد."}.get(kw.get('done')),
            'sides': ikiku_sides(request.env.user),
            'number': self._number(self._partner()),
        })

    @http.route('/business/name', type='http', auth='user', methods=['GET', 'POST'], website=True, sitemap=False)
    def business_name(self, **post):
        """The first question of کو؟, a further business (?new=1), and renaming one (?business=<id>)."""
        staff = self._staff_elsewhere()
        if staff:
            return staff
        if self._needs_name(self._partner()):
            return request.redirect('/join/name?for=ku')
        businesses = self._businesses()
        if post.get('business'):
            business = self._business(post['business'])
            if not business:
                return request.not_found()
        elif businesses and not post.get('new'):
            business = businesses[0] if len(businesses) == 1 else None
            if not business:
                return request.redirect('/business')
        else:
            business = None
        name = ' '.join((post.get('name') or '').split())
        error = None
        if request.httprequest.method == 'POST':
            if name:
                if business:
                    business.name = name
                    return request.redirect('/business')
                made = self._partner()._ikiku_grant_role('ku', business_name=name, another=bool(businesses))
                remember_side('ku')
                self._keep_draft({'business_id': made.id})
                return request.redirect('/business/need/who')
            error = "اسم رو ننوشتید. اینجا بنویسید."
        else:
            name = business.name if business else ''
        return request.render('ikiku_portal.business_name', {
            'business': business, 'name': name, 'error': error, 'another': bool(businesses) and not business,
            'has_resource': 'ki' in ikiku_sides(request.env.user)})

    @http.route('/business/need/who', type='http', auth='user', methods=['GET', 'POST'], website=True,
                sitemap=False)
    def need_who(self, **post):
        business, elsewhere = self._need_business()
        if elsewhere:
            return elsewhere
        draft = self._draft()
        raw = (post.get('raw') or '').strip()
        error = None
        if request.httprequest.method == 'POST':
            node = request.env['ikiku.spec.node'].sudo().browse(to_int(post.get('node_id'), 0)).exists()
            if node and node.kind == 'competency':
                position = request.env['ikiku.position'].sudo().search(
                    [('business_id', '=', business.id), ('spec_node_id', '=', node.id)], limit=1)
                if not position:
                    position = request.env['ikiku.position'].sudo().steer(business, raw or node.name, chosen_node=node)
                elif raw and node not in self._resolve(raw):
                    request.env['ikiku.spec.candidate'].sudo().record(
                        raw, partner=request.env.user.partner_id, source='ikiku.business', res_id=business.id)
                draft['position_id'] = position.id
                draft['node_id'] = node.id
                self._keep_draft(draft)
                return request.redirect('/business/need/type')
            error = "یکی رو انتخاب کنید."
        return self._business_page('ikiku_portal.need_who', 1, {
            'groups': self._competencies(), 'raw': raw, 'selected': draft.get('node_id'),
            'proposals': self._resolve(raw) if raw and request.httprequest.method == 'GET' else None,
            'error': error})

    @http.route('/business/need/type', type='http', auth='user', methods=['GET', 'POST'], website=True,
                sitemap=False)
    def need_type(self, **post):
        draft = self._draft()
        if not draft.get('position_id'):
            return request.redirect('/business/need/who')
        WorkType = request.env['ikiku.work.type'].sudo()
        error = None
        if request.httprequest.method == 'POST':
            work_type = WorkType.browse(to_int(post.get('work_type_id'), 0)).exists()
            if work_type:
                draft['work_type_id'] = work_type.id
                self._keep_draft(draft)
                return request.redirect('/business/need/count')
            error = "یکی رو انتخاب کنید."
        return self._business_page('ikiku_portal.need_type', 2, {
            'work_types': WorkType.search([]), 'selected': draft.get('work_type_id'), 'error': error})

    @http.route('/business/need/count', type='http', auth='user', methods=['GET', 'POST'], website=True,
                sitemap=False)
    def need_count(self, **post):
        draft = self._draft()
        if not draft.get('work_type_id'):
            return request.redirect(self._need_missing(draft) or '/business/need/type')
        seats = to_int(post.get('seats'), draft.get('seats') or 1)
        error = None
        if request.httprequest.method == 'POST':
            adjust = to_int(post.get('adjust'), 0)
            if adjust:
                seats = max(1, min(MAX_SEATS, seats + adjust))
            elif 1 <= seats <= MAX_SEATS:
                draft['seats'] = seats
                self._keep_draft(draft)
                return request.redirect('/business/need/when')
            else:
                error = "باید بین ۱ و ۵۰ نفر باشه."
        return self._business_page('ikiku_portal.need_count', 3, {
            'seats': seats, 'seats_fa': to_fa_digits(seats), 'error': error})

    @http.route('/business/need/when', type='http', auth='user', methods=['GET', 'POST'], website=True,
                sitemap=False)
    def need_when(self, **post):
        draft = self._draft()
        if not draft.get('seats'):
            return request.redirect(self._need_missing(draft) or '/business/need/count')
        error = None
        if request.httprequest.method == 'POST':
            start, end, error = read_dates(post)
            if not error:
                draft.update({'date_start': start.isoformat(), 'date_end': end.isoformat() if end else False})
                self._keep_draft(draft)
                return request.redirect('/business/need/where')
        if request.httprequest.method == 'POST':
            values = dict(post)
        elif draft.get('date_start'):
            values = dates_values(date.fromisoformat(draft['date_start']),
                                  date.fromisoformat(draft['date_end']) if draft.get('date_end') else None)
        else:
            values = {}
        return self._business_page('ikiku_portal.need_when', 4, {
            'dates': date_widget('business', values), 'error': DATE_ERRORS.get(error)})

    @http.route('/business/need/where', type='http', auth='user', methods=['GET', 'POST'], website=True,
                sitemap=False)
    def need_where(self, **post):
        business, elsewhere = self._need_business()
        if elsewhere:
            return elsewhere
        draft = self._draft()
        missing = self._need_missing(draft)
        if missing:
            return request.redirect(missing)
        last = request.env['ikiku.demand'].sudo().search([('business_id', '=', business.id)],
                                                         order='create_date desc', limit=1)
        errors = {}
        if request.httprequest.method == 'POST':
            province_id = to_int(post.get('province_id'))
            city = ' '.join((post.get('city') or '').split())
            province = request.env['ikiku.province'].sudo().browse(province_id or 0).exists()
            if not province:
                errors['province'] = "استان رو انتخاب نکردید."
            if not city:
                errors['city'] = "شهر رو ننوشتید."
            position = request.env['ikiku.position'].sudo().browse(draft['position_id']).exists()
            if position.business_id != business:
                return request.redirect('/business/need/who')
            editing = self._own_need(draft['edit_id']) if draft.get('edit_id') else None
            if draft.get('edit_id') and not editing:
                request.session.pop('ikiku_need', None)
                return request.redirect('/business')
            if not errors and editing:
                try:
                    editing.ikiku_apply_change({
                        'position_id': position.id, 'work_type_id': draft['work_type_id'], 'seats': draft['seats'],
                        'date_start': date.fromisoformat(draft['date_start']),
                        'date_end': date.fromisoformat(draft['date_end']) if draft.get('date_end') else False,
                        'province_id': province.id, 'city': city,
                    })
                except UserError:
                    request.session.pop('ikiku_need', None)
                    return request.redirect('/business/need/%d' % editing.id)
                request.session.pop('ikiku_need', None)
                return request.redirect('/business?done=changed')
            if not errors:
                demand = request.env['ikiku.demand'].sudo().create({
                    'business_id': business.id,
                    'position_id': position.id,
                    'work_type_id': draft['work_type_id'],
                    'seats': draft['seats'],
                    'date_start': draft['date_start'],
                    'date_end': draft['date_end'] or False,
                    'province_id': province.id,
                    'city': city,
                    'state': 'open',
                })
                if not business.province_id:
                    # A café's first need teaches it its place; the holder's own place stays.
                    business.write({'province_id': province.id, 'city': city})
                request.session.pop('ikiku_need', None)
                request.env['ikiku.proposal'].sudo().build_for_demand(demand)
                return request.redirect('/business/need/%d' % demand.id)
        else:
            partner = self._partner()
            if draft.get('edit_id'):
                last = self._own_need(draft['edit_id']) or last
            province_id = (last.province_id or business.province_id or partner.ikiku_province_id).id
            city = last.city or business.city or partner.ikiku_city or ''
        node = request.env['ikiku.spec.node'].sudo().browse(draft.get('node_id') or 0).exists()
        work_type = request.env['ikiku.work.type'].sudo().browse(draft['work_type_id']).exists()
        today = tehran_today()
        start = date.fromisoformat(draft['date_start'])
        end = date.fromisoformat(draft['date_end']) if draft.get('date_end') else None
        return self._business_page('ikiku_portal.need_where', 5, {
            'provinces': request.env['ikiku.province'].sudo().search([]),
            'cities': self._city_suggestions(),
            'province_id': province_id, 'city': city, 'errors': errors,
            'has_resource': 'ki' in ikiku_sides(request.env.user),
            'summary': {
                'seats': to_fa_digits(draft['seats']),
                'who': node.plain_label or node.name if node else '',
                'type': work_type.name,
                'dates': dates_text(start, end, today),
            }})

    @http.route('/business/need/<int:need_id>', type='http', auth='user', website=True, sitemap=False)
    def need_saved(self, need_id, **kw):
        demand = self._own_need(need_id)
        if not demand:
            return request.not_found()
        return request.render('ikiku_portal.need_saved', {
            'demand': demand, 'seats': to_fa_digits(demand.seats),
            'dates': dates_text(demand.date_start, demand.date_end, tehran_today()),
            'is_open': demand.state in ('open', 'proposed'),
            'booked': bool(demand.ikiku_live_bookings()),
        })

    @http.route('/business/need/new', type='http', auth='user', website=True, sitemap=False)
    def need_new(self, business=None, **kw):
        """A fresh need, for the business named or the only one: nothing left over from a
        change that was not finished."""
        request.session.pop('ikiku_need', None)
        chosen = self._business(business) if business else self._business()
        if chosen:
            self._keep_draft({'business_id': chosen.id})
        return request.redirect('/business/need/who')

    @http.route('/business/need/for', type='http', auth='user', website=True, sitemap=False)
    def need_for(self, business=None, **kw):
        """«برای کدوم کافه؟» for a person with several businesses. The rest of the draft (a role
        chosen on the home page) is kept."""
        businesses = self._businesses()
        if not businesses:
            return request.redirect('/business/name')
        chosen = self._business(business) if business else None
        if chosen:
            draft = self._draft()
            draft['business_id'] = chosen.id
            self._keep_draft(draft)
            return request.redirect('/business/need/who')
        return request.render('ikiku_portal.need_for', {'businesses': businesses})

    def _changeable(self, need_id):
        demand = self._own_need(need_id)
        if not demand:
            return None, request.not_found()
        if demand.state not in ('open', 'proposed') or demand.ikiku_live_bookings():
            return None, request.redirect('/business/need/%d' % demand.id)
        return demand, None

    @http.route('/business/need/<int:need_id>/edit', type='http', auth='user', website=True, sitemap=False)
    def need_edit(self, need_id, **kw):
        """Change a need through the same five questions, each already answered."""
        demand, refusal = self._changeable(need_id)
        if refusal:
            return refusal
        self._keep_draft({
            'edit_id': demand.id,
            'business_id': demand.business_id.id,
            'position_id': demand.position_id.id,
            'node_id': demand.position_id.spec_node_id.id,
            'work_type_id': demand.work_type_id.id,
            'seats': demand.seats,
            'date_start': demand.date_start.isoformat(),
            'date_end': demand.date_end.isoformat() if demand.date_end else False,
        })
        return request.redirect('/business/need/who')

    @http.route('/business/need/<int:need_id>/close', type='http', auth='user', methods=['GET', 'POST'],
                website=True, sitemap=False)
    def need_close(self, need_id, **post):
        """«دیگه لازم ندارم»: found the people, or cancel. Two different ends."""
        demand, refusal = self._changeable(need_id)
        if refusal:
            return refusal
        if request.httprequest.method == 'POST' and post.get('outcome') == 'found':
            demand.ikiku_mark_filled()
            return request.redirect('/business?done=filled')
        return request.render('ikiku_portal.need_close', {'demand': demand, 'seats': to_fa_digits(demand.seats)})

    @http.route('/business/need/<int:need_id>/cancel', type='http', auth='user', methods=['GET', 'POST'],
                website=True, sitemap=False)
    def need_cancel(self, need_id, **post):
        """A cancellation is not complete without a written reason (operator, 2026-09-16)."""
        demand, refusal = self._changeable(need_id)
        if refusal:
            return refusal
        reason = ' '.join((post.get('reason') or '').split())[:1000]
        error = None
        if request.httprequest.method == 'POST':
            if reason:
                demand.ikiku_cancel(reason)
                return request.redirect('/business?done=cancelled')
            error = "دلیل رو بنویسید. بدونِ دلیل لغو نمیشه."
        return request.render('ikiku_portal.need_cancel', {'demand': demand, 'reason': reason, 'error': error})
