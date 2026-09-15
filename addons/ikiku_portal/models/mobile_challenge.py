# Part of iKiKu. Licensed under AGPL-3.0.
"""Proving a mobile number before it becomes the identity anchor.

Phone is the establishing anchor (docs/design.html) and ikiku_mobile is UNIQUE,
so writing whatever number a visitor types would let anyone take somebody else's
number first. With an SMS provider's verification template configured (Kavenegar
or sms.ir, reached through sms_otp, which names neither), the number waits here
until its owner types the code sent to it; only then is it written to the
partner. Proving a number proves the SIM, not the person: ikiku_is_verified
stays a staff decision.

The code is kept as an HMAC keyed by the database secret. The plain code exists
only until the background job has handed it to the provider, because a job
cannot send what it cannot read. An outside API can take seconds to answer (every
lookup from the production host took 8 s until its resolver was fixed on
2026-09-15), so sending never happens inside the visitor's request: the page
waits at most WAIT_LIMIT for the result and shows it the moment it is known.
"""
import hashlib
import hmac
import secrets
from datetime import timedelta

from odoo import api, fields, models

from odoo.addons.sms_otp.tools.otp import SmsOtpError

CODE_DIGITS = 6
CODE_TTL = timedelta(minutes=5)
MAX_TRIES = 5
RESEND_AFTER = timedelta(seconds=60)
MAX_SENDS_PER_HOUR = 3
WAIT_LIMIT = timedelta(minutes=2)
KEEP = timedelta(days=1)

TO_ASCII_DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')

# What the visitor reads. Keys travel in URLs; sentences never do.
MESSAGES = {
    'queued': "کد در راه است…",
    'sent': "کد فرستاده شد. تا پنج دقیقه معتبر است.",
    'wrong': "کد درست نبود.",
    'expired': "این کد دیگر معتبر نیست. کدِ تازه بخواهید.",
    'tries': "کد چند بار اشتباه وارد شد. کدِ تازه بخواهید.",
    'limit': "در یک ساعتِ گذشته برای این شماره به اندازهٔ کافی کد فرستاده‌ایم. کمی بعد دوباره امتحان کنید.",
    'taken': "این شماره پیش‌تر برای حسابِ دیگری تأیید شده است. اگر شمارهٔ شماست، با ایکیکو تماس بگیرید.",
    'held': "این شماره پیش‌تر ثبت شده است.",
    'timeout': "پیامک در دو دقیقه فرستاده نشد. دوباره بخواهید.",
    'failed': "پیامک فرستاده نشد. کمی بعد دوباره بخواهید.",
    'number': "این شماره پیامک نمی‌پذیرد. شماره را دوباره بنویسید.",
    'mobile': "شمارهٔ موبایلِ ایران معتبر نیست.",
}


class IkikuMobileChallenge(models.Model):
    _name = 'ikiku.mobile.challenge'
    _description = "تأییدِ شمارهٔ موبایل"
    _order = 'id desc'

    partner_id = fields.Many2one('res.partner', string="شخص", required=True, ondelete='cascade', index=True)
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

    @api.model
    def _enabled(self):
        return self.env.company._sms_otp_ready()

    @api.model
    def _hash(self, code):
        secret = self.env['ir.config_parameter'].sudo().get_param('database.secret')
        return hmac.new(secret.encode(), code.encode(), hashlib.sha256).hexdigest()

    @api.model
    def _latest(self, partner):
        return self.search([('partner_id', '=', partner.id), ('state', '!=', 'done')], limit=1)

    @api.model
    def _verified_elsewhere(self, partner, mobile):
        return bool(self.env['res.partner'].sudo().with_context(active_test=False).search_count([
            ('ikiku_mobile', '=', mobile), ('ikiku_mobile_verified_on', '!=', False),
            ('id', '!=', partner.id)], limit=1))

    @api.model
    def start(self, partner, mobile):
        """Ask for a code for `mobile`. Returns (challenge, error key or False)."""
        now = fields.Datetime.now()
        latest = self._latest(partner)
        if (latest and latest.mobile == mobile and latest.state in ('queued', 'sent')
                and now - (latest.sent_at or latest.queued_at) < RESEND_AFTER):
            return latest, False
        if self.search_count([('mobile', '=', mobile), ('queued_at', '>=', now - timedelta(hours=1))]) \
                >= MAX_SENDS_PER_HOUR:
            return latest, 'limit'
        if self._verified_elsewhere(partner, mobile):
            return latest, 'taken'
        self.search([('partner_id', '=', partner.id), ('state', 'in', ('queued', 'sent', 'failed'))]).write(
            {'state': 'expired', 'pending_code': False})
        code = '%0*d' % (CODE_DIGITS, secrets.randbelow(10 ** CODE_DIGITS))
        challenge = self.create({'partner_id': partner.id, 'mobile': mobile,
                                 'code_hash': self._hash(code), 'pending_code': code})
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
        """Returns an error key, or False once the number is the partner's anchor."""
        self.ensure_one()
        self._payload()
        if self.state != 'sent':
            return (self.failure or 'failed') if self.state == 'failed' else 'expired'
        if self.tries >= MAX_TRIES:
            self.state = 'expired'
            return 'tries'
        self.tries += 1
        typed = ''.join(ch for ch in (code or '').translate(TO_ASCII_DIGITS) if ch.isdigit())
        if not hmac.compare_digest(self.code_hash, self._hash(typed)):
            if self.tries >= MAX_TRIES:
                self.state = 'expired'
                return 'tries'
            return 'wrong'
        return self._claim()

    def _claim(self):
        self.ensure_one()
        if self._verified_elsewhere(self.partner_id, self.mobile):
            self.state = 'expired'
            return 'taken'
        holder = self.env['res.partner'].sudo().with_context(active_test=False).search(
            [('ikiku_mobile', '=', self.mobile), ('id', '!=', self.partner_id.id)])
        if holder:
            # An unproven claim on the number gives way to its proven owner.
            holder.ikiku_mobile = False
            holder.flush_recordset(['ikiku_mobile'])
            holder.message_post(body="شمارهٔ موبایلِ تأییدنشدهٔ این حساب برداشته شد: "
                                     "صاحبِ شماره آن را با کدِ پیامک برای حسابِ دیگری تأیید کرد.")
        self.partner_id.sudo().write({'ikiku_mobile': self.mobile,
                                      'ikiku_mobile_verified_on': fields.Datetime.now()})
        self.state = 'done'
        return False
