# Part of iKiKu. Licensed under AGPL-3.0.
"""A small client for the sms.ir REST API, version 1 (https://sms.ir/rest-api/).

Every call goes to https://api.sms.ir/v1/... with the key in the X-API-KEY header
and JSON both ways. The answer is {"status", "message", "data"}; anything but
status 1 is an error, and the HTTP code (401, 429, ...) only repeats it.

Two things sms.ir does not have shape the modules above this file:

- NO DELIVERY CALLBACK is documented, so delivery status is only polled.
- NO CLIENT MESSAGE ID. Kavenegar refuses a local id it has already seen, which
  makes a retry safe; sms.ir cannot tell a retry from a new message. So an error
  says whether the request may have been sent (`maybe_sent`): only a failure
  before the request left this machine is known to have sent nothing.

The key travels in a header, not in the URL, but errors still keep only the
exception's type, as the Kavenegar client does.
"""
import re

import requests
from urllib3.exceptions import NewConnectionError

from odoo.addons.sms_otp.tools.otp import SmsOtpError

API_ROOT = 'https://api.sms.ir/v1'
TIMEOUT = 30

# Mobiles, and texts, per send request.
SEND_LIMIT = 100

# deliveryState in a report.
STATE_DELIVERED = 1
STATE_AT_OPERATOR = (3, 5)
STATE_FAILED = (2, 4, 6)
STATE_BLACKLISTED = 7
STATE_FINAL = (STATE_DELIVERED, STATE_BLACKLISTED) + STATE_FAILED

PACK_ID_RE = re.compile(r'^[0-9A-Fa-f-]{32,36}$')


class SmsIrError(SmsOtpError):
    """`status` is sms.ir's status, or 0 when no readable answer came back."""

    provider = 'smsir'
    # 104 invalid mobile numbers, 115 numbers on the blacklist.
    BAD_NUMBER_STATUSES = (104, 115)

    def __init__(self, method, status, message, maybe_sent=False):
        super().__init__(method, status, message)
        self.maybe_sent = maybe_sent


def never_sent(error):
    """True when a requests error came before the request reached sms.ir: no
    connection, or no TLS session to write it into."""
    if isinstance(error, (requests.exceptions.ConnectTimeout, requests.exceptions.SSLError)):
        return True
    if isinstance(error, requests.exceptions.ConnectionError):
        reason = getattr(error.args[0], 'reason', None) if error.args else None
        return isinstance(reason, NewConnectionError)
    return False


def local_mobile(number):
    """sms.ir's examples write Iranian mobiles as 09121234567; Odoo keeps them as
    +989121234567. Other numbers pass as their digits."""
    digits = ''.join(str(int(ch)) for ch in number or '' if ch.isdecimal())
    if digits.startswith('0098'):
        digits = digits[4:]
    elif digits.startswith('98') and len(digits) == 12:
        digits = digits[2:]
    if len(digits) == 10 and digits.startswith('9'):
        return '0' + digits
    return digits


class SmsIrClient:

    def __init__(self, api_key, endpoint=API_ROOT, session=None, timeout=TIMEOUT):
        self.api_key = (api_key or '').strip()
        self.endpoint = (endpoint or API_ROOT).rstrip('/')
        self.session = session or requests.Session()
        self.timeout = timeout

    def call(self, verb, path, payload=None):
        if not self.api_key:
            raise SmsIrError(path, 10, "no API key")
        try:
            response = self.session.request(
                verb, self.endpoint + path, json=payload, timeout=self.timeout,
                headers={'X-API-KEY': self.api_key, 'Accept': 'application/json'})
        except requests.exceptions.RequestException as e:
            raise SmsIrError(path, 0, type(e).__name__, maybe_sent=not never_sent(e)) from None
        try:
            body = response.json()
            status = int(body['status'])
            message = body.get('message') or ''
        except (ValueError, KeyError, TypeError):
            # Something answered, so the request arrived; whether it was acted on is unknown.
            raise SmsIrError(path, 0, "unreadable answer (HTTP %s)" % response.status_code,
                             maybe_sent=True) from None
        if status != 1:
            raise SmsIrError(path, status, message)
        return body.get('data')

    def send_like_to_like(self, line_number, mobiles, texts):
        """One text per mobile, in the same order. Answers {packId, messageIds, cost}."""
        return self.call('POST', '/send/likeToLike', {
            'lineNumber': int(line_number), 'mobiles': list(mobiles), 'messageTexts': list(texts)})

    def verify(self, mobile, template_id, parameters):
        """Send an approved verification template; `parameters` maps each #NAME# in
        it to its value (25 characters at most). Answers {messageId, cost}."""
        return self.call('POST', '/send/verify', {
            'mobile': mobile, 'templateId': int(template_id),
            'parameters': [{'name': name, 'value': str(value)} for name, value in parameters.items()]})

    def pack_report(self, pack_id):
        """Every message of one send request, each with its deliveryState."""
        if not PACK_ID_RE.match(pack_id or ''):
            raise SmsIrError('/send/pack', 16, "not a pack id")
        return self.call('GET', '/send/pack/%s' % pack_id)

    def credit(self):
        return self.call('GET', '/credit')

    def lines(self):
        return self.call('GET', '/line')
