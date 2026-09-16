# Part of iKiKu. Licensed under AGPL-3.0.
"""The way in: a mobile number and an SMS code (operator, 2026-09-16, D-1 B).

A visitor types a number, gets a code, types the code, and is signed in: to the
account that proved the number before, to an account staff made for that number,
or to a new one. Email and password stay for staff and for accounts that already
use them (/web/login); public email signup is closed in models/website.py.

A signed-in account without a proven number uses the same two screens to prove it.
Errors re-render the form with what was typed, so a number never travels in a URL.

One account may hold both sides (operator, 2026-09-16): a worker page (کی؟, /me) and a
business (کو؟, /business). Where a person lands is decided here, in one place.

Odoo's own /web/login offers the same SMS sign-in above its email form. The box posts
to /enter/send and the code is typed on /enter/code, so every limit, the reuse of the
last code and the refusal of staff numbers apply unchanged; the page's ?redirect= and
any error wait in the session, never in a URL.
"""
from urllib.parse import urlencode

from odoo import http
from odoo.exceptions import ValidationError
from odoo.http import request

from odoo.addons.ikiku_portal.controllers.common import mask
from odoo.addons.ikiku_portal.models.mobile_challenge import MESSAGES
from odoo.addons.portal.controllers.portal import CustomerPortal
from odoo.addons.web.controllers.utils import _get_login_redirect_url
from odoo.addons.website.controllers.main import Website

ROLES = ('ki', 'ku')
SIDE_HOME = {'ki': '/me', 'ku': '/business'}
SIDE_START = {'ki': '/join', 'ku': '/business/name'}
CHOOSE = '/my'
SESSION_SIDE = 'ikiku_side'
SESSION_NEXT = 'ikiku_enter_next'
SESSION_LOGIN_SMS = 'ikiku_login_sms'


def ikiku_sides(user):
    """The sides an iKiKu portal account holds, in a fixed order: ('ki',), ('ku',), both or none."""
    if user._is_public() or not user.share:
        return ()
    env, partner = request.env, user.partner_id
    sides = []
    if env['ikiku.resource'].sudo().search_count([('partner_id', '=', partner.id)], limit=1):
        sides.append('ki')
    if env['ikiku.business'].sudo().search_count(
            [('partner_id', '=', partner.commercial_partner_id.id)], limit=1):
        sides.append('ku')
    return tuple(sides)


def remember_side(side):
    """The side last opened, for this browser only: it decides where /my goes next time."""
    request.session[SESSION_SIDE] = side


def ikiku_home_for(user, side=None):
    """Where an iKiKu portal user belongs, or False for anyone else. With `side`, only that
    side's page. A person with both sides goes to the side last opened here, or to /my,
    which asks."""
    sides = ikiku_sides(user)
    if side:
        return SIDE_HOME[side] if side in sides else False
    if not sides:
        return False
    if len(sides) == 1:
        return SIDE_HOME[sides[0]]
    last = request.session.get(SESSION_SIDE)
    return SIDE_HOME[last] if last in sides else CHOOSE


def safe_redirect(url):
    """A path on this site, or None."""
    if not url or not isinstance(url, str) or len(url) > 512:
        return None
    if not url.startswith('/') or url.startswith('//') or '\\' in url:
        return None
    return url


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
        """After signing in. A named door (role) wins: its page, or its door when the person
        holds only the other side, so they are asked before a second side is made."""
        if role:
            if ikiku_home_for(user, role):
                return SIDE_HOME[role]
            return '/' + role if ikiku_sides(user) else SIDE_START[role]
        return ikiku_home_for(user) or '/join'

    def _after_sign_in(self, user, role, nxt):
        redirect = safe_redirect(nxt.get('redirect'))
        if redirect in ('/', CHOOSE) or (redirect and user.share and redirect.startswith(('/odoo', '/web'))):
            redirect = None
        if redirect:
            return redirect
        if nxt.get('from') == 'login' and not role and not ikiku_sides(user):
            return '/#ikiku-doors'
        return self._next(user, role)

    def _back_to_login(self, mobile, error, redirect):
        request.session[SESSION_LOGIN_SMS] = {'mobile': (mobile or '')[:20], 'error': error}
        query = {'sms': 1}
        if safe_redirect(redirect):
            query['redirect'] = redirect
        return request.redirect('/web/login?' + urlencode(query))

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
        # A bare /enter names no side: a café owner signing in must not become a worker.
        role = kw.get('as') if kw.get('as') in ROLES else None
        user = request.env.user
        request.session.pop(SESSION_NEXT, None)
        if user._is_public():
            self._session_key()
        elif user.partner_id.sudo().ikiku_mobile_verified_on:
            return request.redirect(self._next(user, role))
        return self._render_mobile(role, error=MESSAGES.get(kw.get('error')))

    @http.route('/enter/send', type='http', auth='public', methods=['POST'], website=True,
                csrf=True, sitemap=False)
    def enter_send(self, mobile=None, role=None, origin=None, redirect=None, **post):
        role = role if role in ROLES else None
        from_login = origin == 'login'
        if from_login:
            request.session[SESSION_NEXT] = {'from': 'login', 'redirect': safe_redirect(redirect)}
        else:
            request.session.pop(SESSION_NEXT, None)

        def refuse(sentence):
            if from_login:
                return self._back_to_login(mobile, sentence, redirect)
            return self._render_mobile(role, mobile, sentence)

        Challenge = request.env['ikiku.mobile.challenge'].sudo()
        if not Challenge._enabled():
            return refuse(MESSAGES['failed'])
        try:
            normalised = request.env['res.partner'].sudo().normalise_mobile(mobile)
        except ValidationError:
            normalised = False
        if not normalised:
            return refuse(MESSAGES['mobile'])
        user = request.env.user
        if user._is_public():
            _challenge, error = Challenge.start(False, normalised, session_key=self._session_key(),
                                                as_role=role)
        else:
            _challenge, error = Challenge.start(user.partner_id, normalised)
        if error == 'limit':
            at = Challenge.retry_at(normalised)
            return refuse(MESSAGES['limit_at'] % at if at else MESSAGES['limit'])
        if error:
            return refuse(MESSAGES.get(error, MESSAGES['failed']))
        return request.redirect('/enter/code' + ('?note=reused' if _challenge.env.context.get('ikiku_reused') else ''))

    @http.route('/enter/code', type='http', auth='public', website=True, sitemap=False)
    def enter_code(self, **kw):
        challenge = self._challenge()
        if not challenge:
            return request.redirect('/enter')
        nxt = request.session.get(SESSION_NEXT) or {}
        if nxt.get('from') == 'login':
            back_url = '/web/login' + ('?' + urlencode({'redirect': nxt['redirect']}) if nxt.get('redirect') else '')
        else:
            back_url = '/enter' + ('?as=%s' % challenge.as_role if challenge.as_role else '')
        return request.render('ikiku_portal.enter_code', {
            'challenge': challenge,
            'status': challenge._payload(),
            'masked': mask(challenge.mobile),
            'role': challenge.as_role or None,
            'back_url': back_url,
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
        nxt = request.session.get(SESSION_NEXT) or {}
        error = challenge.check(code)
        if error:
            return request.redirect('/enter/code?' + urlencode({'error': error}))
        request.session.pop(SESSION_NEXT, None)
        if challenge.purpose == 'verify':
            return request.redirect(ikiku_home_for(request.env.user) or '/join')
        role = challenge.as_role or None
        user, token, error = challenge._issue_login()
        if error:
            if nxt.get('from') == 'login':
                return self._back_to_login('', MESSAGES['staff_here'] if error == 'staff'
                                           else MESSAGES.get(error, MESSAGES['failed']), nxt.get('redirect'))
            return request.redirect('/enter?' + urlencode(dict({'error': error}, **({'as': role} if role else {}))))
        request.session.authenticate(request.env, {'type': 'ikiku_sms', 'login': user.login, 'token': token})
        return request.redirect(_get_login_redirect_url(user.id, self._after_sign_in(user, role, nxt)))

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

    @http.route()
    def web_login(self, *args, **kw):
        """Odoo's login page, with the SMS sign-in above its email form (templates:
        ikiku_login_templates.xml). Email and password work exactly as before."""
        response = super().web_login(*args, **kw)
        if not getattr(response, 'is_qweb', False):
            return response
        enabled = request.env['ikiku.mobile.challenge'].sudo()._enabled()
        public = request.env.user._is_public()
        if enabled and public:
            request.session['ikiku_enter'] = True
        stored = (request.session.pop(SESSION_LOGIN_SMS, None) if kw.get('sms') else None) or {}
        hint = None
        login = kw.get('login') or ''
        if request.httprequest.method == 'POST' and response.qcontext.get('error') and '@' not in login:
            try:
                if request.env['res.partner'].sudo().normalise_mobile(login):
                    hint = MESSAGES['login_is_mobile']
            except ValidationError:
                pass
        response.qcontext.update({
            'ikiku_otp_enabled': enabled,
            'ikiku_is_public': public,
            'ikiku_sms_mobile': stored.get('mobile', ''),
            'ikiku_sms_error': stored.get('error'),
            'ikiku_login_hint': hint,
        })
        return response


class IkikuCustomerPortal(CustomerPortal):

    @http.route()
    def home(self, **kw):
        user = request.env.user
        sides = ikiku_sides(user)
        if len(sides) == 2 and request.session.get(SESSION_SIDE) not in sides:
            business = request.env['ikiku.business'].sudo().search(
                [('partner_id', '=', user.partner_id.commercial_partner_id.id)], limit=1)
            return request.render('ikiku_portal.choose_side', {'business': business})
        target = ikiku_home_for(user)
        if target:
            return request.redirect(target)
        if user.share and user.partner_id.sudo().ikiku_mobile:
            # An iKiKu account with no side yet: the two doors, not Odoo's portal.
            return request.redirect('/#ikiku-doors')
        return super().home(**kw)

    @http.route()
    def account(self, **kw):
        target = ikiku_home_for(request.env.user)
        return request.redirect(target) if target else super().account(**kw)
