# Part of iKiKu. Licensed under AGPL-3.0.
"""Proving a mobile number, to sign in with it or to anchor an account to it.

Phone is the establishing anchor (docs/design.html) and ikiku_mobile is UNIQUE,
so writing whatever number a visitor types would let anyone take somebody else's
number first. A number becomes an account's anchor only once its owner types the
code sent to it. Proving a number proves the SIM, not the person:
ikiku_is_verified stays a staff decision.

Two purposes share one mechanism:
  verify  a signed-in account proves its number (the older email accounts).
  enter   a visitor proves a number to sign in or to sign up (operator, 2026-09-16,
          D-1 B). The challenge is bound to the browser session, not to a partner,
          and a proven code issues a single-use login token that only a portal
          user can spend (res_users._check_credentials).

Which account a proven number opens, in order:
  1. the account that already proved this number;
  2. an account whose number staff wrote (a staff-created account, D-8, or a
     staff number change, D-7): whoever proves the SIM is the person staff met;
  3. otherwise a new account, with an opaque login (D-2 B). Unproven numbers that
     other accounts merely typed give way, as they always have.
A number proven for a staff (internal) account never opens anything here.

The code is kept as an HMAC keyed by the database secret. The plain code exists
only until the background job has handed it to the provider. Sending never
happens inside the visitor's request: the page waits at most WAIT_LIMIT and shows
the result the moment it is known.
"""
import hashlib
import hmac
import secrets
from datetime import timedelta

from odoo import api, fields, models

from odoo.addons.ikiku_base.models.jalali import to_fa_digits, to_latin_digits
from odoo.addons.sms_otp.tools.otp import SmsOtpError

CODE_DIGITS = 6
# A code works for a day (operator, 2026-09-16): an SMS that arrives late, or a visitor
# who comes back tomorrow, can still use the last code instead of paying for a new one.
CODE_TTL = timedelta(hours=24)
MAX_TRIES = 5
RESEND_AFTER = timedelta(seconds=60)
MAX_SENDS_PER_HOUR = 10
WAIT_LIMIT = timedelta(minutes=2)
# Challenges are deleted a day after their code stops working, never while it works.
KEEP = CODE_TTL + timedelta(days=1)
LOGIN_TOKEN_TTL = timedelta(minutes=2)
# A new SMS account's name until its owner writes their own on the first screen.
NEW_PARTNER_NAME = "کاربرِ تازه"



def duration_text(delta):
    """timedelta(hours=24) -> ۲۴ ساعت, timedelta(minutes=5) -> ۵ دقیقه."""
    seconds = int(delta.total_seconds())
    if seconds >= 3600 and seconds % 3600 == 0:
        return "%s ساعت" % to_fa_digits(seconds // 3600)
    return "%s دقیقه" % to_fa_digits(max(1, seconds // 60))


# What the visitor reads, in spoken, polite Persian (operator, D-9). Keys travel in
# URLs; sentences never do. Every number in them is read from the settings above.
MESSAGES = {
    'queued': "پیامک داره می‌ره…",
    'sent': "پیامک رفت. معمولاً تا یه دقیقه می‌رسه. کد تا %s کار می‌کنه." % duration_text(CODE_TTL),
    'reused': "آخرین کدی که براتون فرستادیم هنوز کار می‌کنه، پس پیامکِ تازه نفرستادیم. همون رو بنویسید؛ "
              "اگه پیداش نمی‌کنید، «دوباره بفرست» رو بزنید.",
    'wrong': "این کد درست نیست. دوباره نگاه کنید و بنویسید.",
    'expired': "وقتِ این کد تموم شد. یه کدِ تازه بخواید.",
    'tries': "چند بار اشتباه شد. یه کدِ تازه بخواید.",
    'limit': "تو یه ساعت فقط %s بار کد می‌فرستیم. کمی بعد دوباره امتحان کنید." % to_fa_digits(MAX_SENDS_PER_HOUR),
    'limit_at': "تو یه ساعت فقط " + to_fa_digits(MAX_SENDS_PER_HOUR) + " بار کد می‌فرستیم. ساعتِ %s دوباره امتحان کنید.",
    'taken': "این شماره مالِ یه حسابِ دیگه‌ست.",
    'held': "این شماره مالِ یه حسابِ دیگه‌ست.",
    'timeout': "پیامک نرفت. دوباره بخواید.",
    'failed': "پیامک نرفت. دوباره بخواید.",
    'number': "این شماره پیامک نمی‌گیره. شماره رو دوباره نگاه کنید.",
    'mobile': "این شماره درست نیست. باید ۱۱ رقم باشه و با ۰۹ شروع بشه. مثلِ ۰۹۱۲۱۲۳۴۵۶۷",
    'staff': "این شماره مالِ حسابِ همکارانِ ایکیکوست. از «ورود با ایمیل» وارد بشید.",
    'session': "این صفحه کهنه شده. شماره رو دوباره بنویسید.",
    'staff_here': "این شماره مالِ حسابِ همکارانِ ایکیکوست. پایینِ همین صفحه با ایمیل و رمز وارد بشید.",
    'login_is_mobile': "اگه با شماره موبایل ثبت‌نام کردید، رمز ندارید: بالای همین صفحه کدِ پیامک بخواید.",
}


class IkikuMobileChallenge(models.Model):
    _name = 'ikiku.mobile.challenge'
    _description = "تأییدِ شمارهٔ موبایل"
    _order = 'id desc'

    partner_id = fields.Many2one('res.partner', string="شخص", ondelete='cascade', index=True,
                                 help="خالی برای ورود یا ثبت‌نام با پیامک: هنوز معلوم نیست حسابِ کیست.")
    purpose = fields.Selection([
        ('verify', "تأییدِ شمارهٔ حساب"),
        ('enter', "ورود یا ثبت‌نام"),
    ], string="برای", default='verify', required=True)
    session_key = fields.Char(index=True, groups='base.group_system',
                              help="اثرِ نشستِ مرورگر؛ کدِ ورود فقط در همان مرورگر کار می‌کند.")
    as_role = fields.Selection([('ki', "نیرو"), ('ku', "کسب‌وکار")], string="از درِ")
    mobile = fields.Char("شماره", required=True, index=True)
    state = fields.Selection([
        ('queued', "در صف"),
        ('sent', "فرستاده شد"),
        ('failed', "فرستاده نشد"),
        ('done', "تأیید شد"),
        ('expired', "باطل شد"),
    ], string="وضعیت", default='queued', required=True)
    failure = fields.Char("علت")
    code_hash = fields.Char(required=True, groups='base.group_system')
    pending_code = fields.Char(groups='base.group_system')
    tries = fields.Integer("تلاش‌ها", default=0)
    queued_at = fields.Datetime("درخواست", required=True, default=fields.Datetime.now)
    sent_at = fields.Datetime("ارسال")
    expires_at = fields.Datetime("انقضا")
    sms_provider = fields.Char("سامانهٔ پیامک")
    sms_messageid = fields.Char("شناسهٔ پیامک")
    login_user_id = fields.Many2one('res.users', string="حسابِ واردشده", readonly=True, ondelete='cascade')
    login_token_hash = fields.Char(groups='base.group_system', readonly=True)
    login_token_expires = fields.Datetime(groups='base.group_system', readonly=True)
    login_token_used = fields.Boolean(groups='base.group_system', readonly=True)

    @api.model
    def _enabled(self):
        return self.env.company._sms_otp_ready()

    @api.model
    def _hash(self, code):
        secret = self.env['ir.config_parameter'].sudo().get_param('database.secret')
        return hmac.new(secret.encode(), code.encode(), hashlib.sha256).hexdigest()

    @api.model
    def session_key_for(self, sid):
        """What the challenge stores about the browser session: a hash, never the sid."""
        return self._hash('session:' + (sid or ''))

    @api.model
    def _latest(self, partner=None, session_key=None):
        if partner:
            domain = [('partner_id', '=', partner.id)]
        elif session_key:
            domain = [('session_key', '=', session_key), ('purpose', '=', 'enter')]
        else:
            return self.browse()
        return self.search(domain + [('state', '!=', 'done')], limit=1)

    @api.model
    def _verified_elsewhere(self, partner, mobile):
        return bool(self.env['res.partner'].sudo().with_context(active_test=False).search_count([
            ('ikiku_mobile', '=', mobile), ('ikiku_mobile_verified_on', '!=', False),
            ('id', '!=', partner.id)], limit=1))

    @api.model
    def retry_at(self, mobile):
        """When the hourly limit on `mobile` lets the next code out, as ۱۴:۲۰ in Tehran."""
        oldest = self.search([('mobile', '=', mobile),
                              ('queued_at', '>=', fields.Datetime.now() - timedelta(hours=1))],
                             order='queued_at', limit=1)
        if not oldest:
            return False
        moment = fields.Datetime.context_timestamp(
            self.with_context(tz='Asia/Tehran'), oldest.queued_at + timedelta(hours=1, minutes=1))
        return to_fa_digits(moment.strftime('%H:%M'))

    @api.model
    def _reusable(self, partner, mobile):
        """The last code sent to `mobile` that still works, if any: for a signed-in partner
        only their own, for sign-in any visitor's. A queued code still on its way counts."""
        now = fields.Datetime.now()
        domain = [('mobile', '=', mobile), ('tries', '<', MAX_TRIES),
                  '|', '&', ('state', '=', 'sent'), ('expires_at', '>', now),
                  '&', ('state', '=', 'queued'), ('queued_at', '>', now - WAIT_LIMIT)]
        domain += [('partner_id', '=', partner.id)] if partner else [('purpose', '=', 'enter')]
        return self.search(domain, order='id desc', limit=1)

    @api.model
    def start(self, partner, mobile, session_key=None, as_role=None, force=False):
        """Ask for a code for `mobile`, for a signed-in `partner` or, with no partner, for
        the browser session `session_key`. Returns (challenge, error key or False).

        Unless `force` (the resend button), the last code that still works is used again
        and no SMS is sent: for sign-in it moves to this browser session, so a code typed
        the next day in another tab still opens the account. A reused challenge carries
        ikiku_reused in its context so the page can say so. A forced resend replaces it,
        so only the last code ever works."""
        now = fields.Datetime.now()
        if not force:
            reusable = self._reusable(partner, mobile)
            if reusable:
                if not partner and session_key and reusable.session_key != session_key:
                    reusable.write({'session_key': session_key, 'as_role': as_role or False})
                return reusable.with_context(ikiku_reused=True), False
        latest = self._latest(partner=partner, session_key=None if partner else session_key)
        if (latest and latest.mobile == mobile and latest.state in ('queued', 'sent')
                and now - (latest.sent_at or latest.queued_at) < RESEND_AFTER):
            return latest, False
        if self.search_count([('mobile', '=', mobile), ('queued_at', '>=', now - timedelta(hours=1))]) \
                >= MAX_SENDS_PER_HOUR:
            return latest, 'limit'
        if partner and self._verified_elsewhere(partner, mobile):
            return latest, 'taken'
        if partner:
            self.search([('partner_id', '=', partner.id), ('state', 'in', ('queued', 'sent', 'failed'))]).write(
                {'state': 'expired', 'pending_code': False})
        elif session_key:
            self.search([('session_key', '=', session_key), ('purpose', '=', 'enter'),
                         ('state', 'in', ('queued', 'sent', 'failed'))]).write(
                {'state': 'expired', 'pending_code': False})
        else:
            return latest, 'session'
        code = '%0*d' % (CODE_DIGITS, secrets.randbelow(10 ** CODE_DIGITS))
        challenge = self.create({
            'partner_id': partner.id if partner else False,
            'purpose': 'verify' if partner else 'enter',
            'session_key': False if partner else session_key,
            'as_role': as_role or False,
            'mobile': mobile,
            'code_hash': self._hash(code), 'pending_code': code,
        })
        self.env.ref('ikiku_portal.ir_cron_ikiku_mobile_challenge_send')._trigger()
        return challenge, False

    @api.model
    def _cron_send(self):
        now = fields.Datetime.now()
        company = self.env.company
        for challenge in self.search([('state', '=', 'queued')], order='id'):
            if now - challenge.queued_at > WAIT_LIMIT:
                challenge.write({'state': 'failed', 'failure': 'timeout', 'pending_code': False})
            else:
                try:
                    provider, messageid = company._sms_otp_send(challenge.mobile, challenge.pending_code)
                except SmsOtpError as e:
                    challenge.write({'state': 'failed', 'pending_code': False, 'sms_provider': e.provider,
                                     'failure': 'number' if e.bad_number else 'failed'})
                else:
                    sent = fields.Datetime.now()
                    challenge.write({'state': 'sent', 'sent_at': sent, 'expires_at': sent + CODE_TTL,
                                     'sms_provider': provider, 'sms_messageid': messageid,
                                     'pending_code': False})
            if self.env.context.get('cron_id'):
                # A sent SMS cannot be taken back: commit it before the next one can fail.
                self.env['ir.cron']._commit_progress(1)
        self.search([('queued_at', '<', now - KEEP)]).unlink()

    def _payload(self):
        """What the page shows, settling a wait or a code that has run out of time."""
        self.ensure_one()
        now = fields.Datetime.now()
        if self.state == 'queued' and now - self.queued_at > WAIT_LIMIT:
            self.write({'state': 'failed', 'failure': 'timeout', 'pending_code': False})
        elif self.state == 'sent' and self.expires_at and now > self.expires_at:
            self.state = 'expired'
        key = (self.failure or 'failed') if self.state == 'failed' else self.state
        if self.state in ('queued', 'sent'):
            resend_in = (self.sent_at or self.queued_at) + RESEND_AFTER - now
        else:
            resend_in = timedelta(0)
        return {
            'state': self.state,
            'text': MESSAGES.get(key, MESSAGES['failed']),
            'wait_left': max(0, int((self.queued_at + WAIT_LIMIT - now).total_seconds()))
            if self.state == 'queued' else 0,
            'resend_in': max(0, int(resend_in.total_seconds())),
        }

    def check(self, code):
        """Returns an error key, or False once the code is proven: for `verify` the number
        is then the partner's anchor; for `enter` the controller calls _issue_login."""
        self.ensure_one()
        self._payload()
        if self.state != 'sent':
            return (self.failure or 'failed') if self.state == 'failed' else 'expired'
        if self.tries >= MAX_TRIES:
            self.state = 'expired'
            return 'tries'
        self.tries += 1
        typed = ''.join(ch for ch in to_latin_digits(code or '') if ch.isascii() and ch.isdigit())
        if not hmac.compare_digest(self.code_hash, self._hash(typed)):
            if self.tries >= MAX_TRIES:
                self.state = 'expired'
                return 'tries'
            return 'wrong'
        if self.purpose == 'enter':
            self.state = 'done'
            return False
        return self._claim()

    def _claim(self):
        self.ensure_one()
        if self._verified_elsewhere(self.partner_id, self.mobile):
            self.state = 'expired'
            return 'taken'
        self._release_unproven(except_partner=self.partner_id)
        self.partner_id.sudo().write({'ikiku_mobile': self.mobile,
                                      'ikiku_mobile_verified_on': fields.Datetime.now()})
        self.state = 'done'
        return False

    def _release_unproven(self, except_partner=None):
        """An unproven claim on the number gives way to its proven owner."""
        domain = [('ikiku_mobile', '=', self.mobile)]
        if except_partner:
            domain.append(('id', '!=', except_partner.id))
        holders = self.env['res.partner'].sudo().with_context(active_test=False).search(domain)
        for holder in holders:
            holder.ikiku_mobile = False
            holder.flush_recordset(['ikiku_mobile'])
            holder.message_post(body="شمارهٔ موبایلِ تأییدنشدهٔ این حساب برداشته شد: "
                                     "صاحبِ شماره آن را با کدِ پیامک برای حسابِ دیگری تأیید کرد.")

    # ------------------------------------------------------------ enter (SMS sign-in)
    def _enter_account(self):
        """The portal user a proven `enter` challenge opens, creating one if needed.
        Returns (user, False) or (False, error key)."""
        self.ensure_one()
        Partner = self.env['res.partner'].sudo().with_context(active_test=False)
        now = fields.Datetime.now()

        proven = Partner.search([('ikiku_mobile', '=', self.mobile),
                                 ('ikiku_mobile_verified_on', '!=', False)], limit=1)
        if proven:
            if proven.user_ids.filtered(lambda u: not u.share):
                return False, 'staff'
            return self._portal_user_for(proven), False

        written_by_staff = Partner.search([('ikiku_mobile', '=', self.mobile),
                                           ('ikiku_mobile_set_by_id', '!=', False)], limit=1)
        if written_by_staff:
            if written_by_staff.user_ids.filtered(lambda u: not u.share):
                return False, 'staff'
            self._release_unproven(except_partner=written_by_staff)
            written_by_staff.write({'ikiku_mobile_verified_on': now})
            written_by_staff.message_post(body="صاحبِ شماره با کدِ پیامک وارد شد و شماره تأیید شد.")
            return self._portal_user_for(written_by_staff), False

        self._release_unproven()
        partner = Partner.create({'name': NEW_PARTNER_NAME, 'ikiku_mobile': self.mobile,
                                  'ikiku_mobile_verified_on': now})
        return self._portal_user_for(partner), False

    def _portal_user_for(self, partner):
        user = partner.with_context(active_test=False).user_ids.filtered('share')[:1]
        if user:
            if not user.active:
                user.active = True
            return user
        return self.env['res.users'].sudo().with_context(no_reset_password=True).create({
            'name': partner.name,
            'partner_id': partner.id,
            # D-2 B: an opaque login. The number stays a restricted partner field instead
            # of appearing in staff user lists, and a number change needs no login change.
            'login': 'm-%s' % secrets.token_hex(8),
            'password': secrets.token_urlsafe(32),
            'group_ids': [(6, 0, [self.env.ref('base.group_portal').id])],
        })

    def _issue_login(self):
        """For a proven `enter` challenge: the account and a single-use login token, or an
        error key. Issued once per challenge."""
        self.ensure_one()
        if self.purpose != 'enter' or self.state != 'done' or self.login_user_id:
            return False, False, 'expired'
        user, error = self._enter_account()
        if error:
            return False, False, error
        token = secrets.token_urlsafe(32)
        self.write({
            'login_user_id': user.id,
            'login_token_hash': self._hash('login:' + token),
            'login_token_expires': fields.Datetime.now() + LOGIN_TOKEN_TTL,
            'login_token_used': False,
        })
        return user, token, False

    @api.model
    def _consume_login_token(self, user, token):
        """True once, for an unexpired token issued to `user`."""
        if not token:
            return False
        challenge = self.sudo().search([
            ('login_user_id', '=', user.id),
            ('login_token_used', '=', False),
            ('login_token_expires', '>', fields.Datetime.now()),
        ], order='id desc', limit=1)
        if not challenge or not hmac.compare_digest(challenge.login_token_hash or '',
                                                    self._hash('login:' + token)):
            return False
        challenge.login_token_used = True
        return True
