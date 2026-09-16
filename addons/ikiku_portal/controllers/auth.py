# Part of iKiKu. Licensed under AGPL-3.0.
"""The way in: a mobile number and an SMS code (operator, 2026-09-16, D-1 B).

A visitor types a number, gets a code, types the code, and is signed in: to the
account that proved the number before, to an account staff made for that number,
or to a new one. Email and password stay for staff and for accounts that already
use them (/web/login); public email signup is closed in models/website.py.

A signed-in account without a proven number uses the same two screens to prove it.
Errors re-render the form with what was typed, so a number never travels in a URL.
"""
from urllib.parse import urlencode

from odoo import http
from odoo.exceptions import ValidationError
from odoo.http import request

from odoo.addons.ikiku_base.models.jalali import to_fa_digits
from odoo.addons.ikiku_portal.models.mobile_challenge import MESSAGES
from odoo.addons.portal.controllers.portal import CustomerPortal
from odoo.addons.website.controllers.main import Website

ROLES = ('ki', 'ku')


def mask(mobile):
    """+989121234567 -> ۰۹۱۲•••۴۵۶۷, for saying where the code went."""
    if not mobile or len(mobile) < 10:
        return ''
    local = '0' + mobile[-10:]
    return to_fa_digits(local[:4]) + '•••' + to_fa_digits(local[-4:])


def ikiku_home_for(user):
    """Where an iKiKu portal user belongs, or False for anyone else."""
    if user._is_public() or not user.share:
        return False
    env = request.env
    partner = user.partner_id
    if env['ikiku.business'].sudo().search_count(
            [('partner_id', '=', partner.commercial_partner_id.id)], limit=1):
        return '/business'
    if env['ikiku.resource'].sudo().search_count([('partner_id', '=', partner.id)], limit=1):
        return '/me'
    return False


class IkikuEnter(http.Controller):

    def _session_key(self):
        # Writing to the session keeps an anonymous session, and the CSRF token tied
        # to it, alive between the number screen and the code screen.
        request.session['ikiku_enter'] = True
        return request.env['ikiku.mobile.challenge'].sudo().session_key_for(request.session.sid)

    def _challenge(self):
        Challenge = request.env['ikiku.mobile.challenge'].sudo()
        if request.env.user._is_public():
            return Challenge._latest(session_key=self._session_key())
        return Challenge._latest(partner=request.env.user.partner_id)

    def _next(self, user, role):
        return ikiku_home_for(user) or ('/business/name' if role == 'ku' else '/join')

    def _render_mobile(self, role, mobile='', error=None):
        user = request.env.user
        return request.render('ikiku_portal.enter_mobile', {
            'role': role,
            'signed_in': not user._is_public(),
            'mobile': (mobile or '')[:20],
            'error': error,
            'otp_enabled': request.env['ikiku.mobile.challenge'].sudo()._enabled(),
        })

    @http.route('/enter', type='http', auth='public', website=True, sitemap=False)
    def enter(self, **kw):
        role = kw.get('as') if kw.get('as') in ROLES else 'ki'
        user = request.env.user
        if user._is_public():
            self._session_key()
        elif user.partner_id.sudo().ikiku_mobile_verified_on:
            return request.redirect(self._next(user, role))
        return self._render_mobile(role, error=MESSAGES.get(kw.get('error')))

    @http.route('/enter/send', type='http', auth='public', methods=['POST'], website=True,
                csrf=True, sitemap=False)
    def enter_send(self, mobile=None, role=None, **post):
        role = role if role in ROLES else 'ki'
        Challenge = request.env['ikiku.mobile.challenge'].sudo()
        if not Challenge._enabled():
            return self._render_mobile(role, mobile, MESSAGES['failed'])
        try:
            normalised = request.env['res.partner'].sudo().normalise_mobile(mobile)
        except ValidationError:
            normalised = False
        if not normalised:
            return self._render_mobile(role, mobile, MESSAGES['mobile'])
        user = request.env.user
        if user._is_public():
            _challenge, error = Challenge.start(False, normalised, session_key=self._session_key(),
                                                as_role=role)
        else:
            _challenge, error = Challenge.start(user.partner_id, normalised)
        if error == 'limit':
            at = Challenge.retry_at(normalised)
            return self._render_mobile(role, mobile, MESSAGES['limit_at'] % at if at else MESSAGES['limit'])
        if error:
            return self._render_mobile(role, mobile, MESSAGES.get(error, MESSAGES['failed']))
        return request.redirect('/enter/code' + ('?note=reused' if _challenge.env.context.get('ikiku_reused') else ''))

    @http.route('/enter/code', type='http', auth='public', website=True, sitemap=False)
    def enter_code(self, **kw):
        challenge = self._challenge()
        if not challenge:
            return request.redirect('/enter')
        return request.render('ikiku_portal.enter_code', {
            'challenge': challenge,
            'status': challenge._payload(),
            'masked': mask(challenge.mobile),
            'role': challenge.as_role or 'ki',
            'error': MESSAGES.get(kw.get('error')),
            'note': MESSAGES['reused'] if kw.get('note') == 'reused' else None,
        })

    @http.route('/enter/code/state', type='http', auth='public', methods=['GET'], sitemap=False)
    def enter_code_state(self, **kw):
        challenge = self._challenge()
        return request.make_json_response(challenge._payload() if challenge else {'state': 'none'})

    @http.route('/enter/code/submit', type='http', auth='public', methods=['POST'], website=True,
                csrf=True, sitemap=False)
    def enter_code_submit(self, code=None, **post):
        challenge = self._challenge()
        if not challenge:
            return request.redirect('/enter')
        error = challenge.check(code)
        if error:
            return request.redirect('/enter/code?' + urlencode({'error': error}))
        if challenge.purpose == 'verify':
            return request.redirect(ikiku_home_for(request.env.user) or '/join')
        role = challenge.as_role or 'ki'
        user, token, error = challenge._issue_login()
        if error:
            return request.redirect('/enter?' + urlencode({'error': error, 'as': role}))
        request.session.authenticate(request.env, {'type': 'ikiku_sms', 'login': user.login, 'token': token})
        return request.redirect(self._next(user, role))

    @http.route('/enter/code/resend', type='http', auth='public', methods=['POST'], website=True,
                csrf=True, sitemap=False)
    def enter_code_resend(self, **post):
        Challenge = request.env['ikiku.mobile.challenge'].sudo()
        latest = self._challenge()
        if not latest or not Challenge._enabled():
            return request.redirect('/enter')
        user = request.env.user
        if user._is_public():
            _challenge, error = Challenge.start(False, latest.mobile, session_key=self._session_key(),
                                                as_role=latest.as_role, force=True)
        else:
            _challenge, error = Challenge.start(user.partner_id, latest.mobile, force=True)
        return request.redirect('/enter/code' + ('?' + urlencode({'error': error}) if error else ''))


class IkikuLoginRedirect(Website):

    def _login_redirect(self, uid, redirect=None):
        """An iKiKu account that signs in with email lands on its own page, not /my."""
        if not redirect:
            redirect = ikiku_home_for(request.env['res.users'].sudo().browse(uid)) or None
        return super()._login_redirect(uid, redirect=redirect)


class IkikuCustomerPortal(CustomerPortal):

    @http.route()
    def home(self, **kw):
        target = ikiku_home_for(request.env.user)
        return request.redirect(target) if target else super().home(**kw)

    @http.route()
    def account(self, **kw):
        target = ikiku_home_for(request.env.user)
        return request.redirect(target) if target else super().account(**kw)
