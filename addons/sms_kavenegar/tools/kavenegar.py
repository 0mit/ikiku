# Part of iKiKu. Licensed under AGPL-3.0.
"""A small client for Kavenegar's REST API (https://kavenegar.com/rest.html).

Every call is POST https://api.kavenegar.com/v1/{API-KEY}/{scope}/{method}.json
with form-encoded parameters; arrays are sent as JSON strings, as Kavenegar's
own Python client does. The answer is {"return": {"status", "message"},
"entries": ...}, and anything but status 200 is an error.

THE API KEY IS IN THE URL PATH. So no URL is ever logged or put in an exception:
a `requests` error's text names the URL it failed on, which is why only the
exception's type is kept.
"""
import json

import requests

API_ROOT = 'https://api.kavenegar.com/v1'
# Measured 8 s per call from the production host in Iran on 2026-09-14.
TIMEOUT = 30

# Per-message delivery status, from Kavenegar's status table.
STATUS_QUEUED = (1, 2)
STATUS_AT_OPERATOR = (4, 5)
STATUS_DELIVERED = 10
STATUS_FAILED = (6, 11, 13)
STATUS_BLOCKED = 14
STATUS_UNKNOWN_ID = 100
STATUS_FINAL = (STATUS_DELIVERED, STATUS_BLOCKED, STATUS_UNKNOWN_ID) + STATUS_FAILED

# Receptors, messages or ids per request.
SEND_LIMIT = 200
STATUS_LIMIT = 500


class KavenegarError(Exception):
    """`status` is Kavenegar's return.status, or 0 when the call never got an answer."""

    def __init__(self, method, status, message):
        super().__init__('%s: %s %s' % (method, status, message))
        self.method = method
        self.status = status
        self.message = message


class KavenegarClient:

    def __init__(self, api_key, endpoint=API_ROOT, session=None, timeout=TIMEOUT):
        self.api_key = (api_key or '').strip()
        self.endpoint = (endpoint or API_ROOT).rstrip('/')
        self.session = session or requests.Session()
        self.timeout = timeout

    def call(self, scope, method, params=None):
        name = '%s/%s' % (scope, method)
        if not self.api_key:
            raise KavenegarError(name, 403, "no API key")
        data = {
            key: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, tuple)) else value
            for key, value in (params or {}).items() if value not in (None, False, '')
        }
        try:
            response = self.session.post(
                '%s/%s/%s.json' % (self.endpoint, self.api_key, name), data=data, timeout=self.timeout)
        except requests.exceptions.RequestException as e:
            raise KavenegarError(name, 0, type(e).__name__) from None
        try:
            body = response.json()
            status = int(body['return']['status'])
            message = body['return'].get('message') or ''
        except (ValueError, KeyError, TypeError):
            raise KavenegarError(name, response.status_code, "unreadable answer") from None
        if status != 200:
            raise KavenegarError(name, status, message)
        return body.get('entries')

    def send_array(self, receptors, senders, messages, local_ids):
        return self.call('sms', 'sendarray', {
            'receptor': list(receptors), 'sender': list(senders),
            'message': list(messages), 'localmessageids': list(local_ids),
        })

    def status(self, message_ids):
        return self.call('sms', 'status', {'messageid': ','.join(str(i) for i in message_ids)})

    def account_info(self):
        return self.call('account', 'info')

    def verify_lookup(self, receptor, template, token, **tokens):
        """Send a pre-approved template: `token` fills %token; token2, token3, token10
        and token20 are the optional others."""
        return self.call('verify', 'lookup', {
            'receptor': receptor, 'template': template, 'token': token, 'type': 'sms', **tokens})
