# Part of iKiKu. Licensed under AGPL-3.0.
"""Odoo's SMS provider interface, answered by Kavenegar.

`sms.sms._send_with_api` hands over messages grouped by body and expects one
result per SMS: {'uuid', 'state', 'failure_reason'}. A state in
sms.sms.IAP_TO_SMS_STATE_SUCCESS is a success; anything else is looked up in
PROVIDER_TO_SMS_FAILURE_TYPE, and a state missing there becomes 'unknown' on the
SMS while the tracker tries `sms_<state>` against Odoo's delivery errors.
"""
import logging

from odoo import _
from odoo.addons.sms.tools.sms_api import SmsApiBase

from . import kavenegar
from .kavenegar import KavenegarError

_logger = logging.getLogger(__name__)

# Kavenegar return.status for a whole request -> the state given to every SMS in it.
RETURN_TO_STATE = {
    401: 'kavenegar_account', 403: 'kavenegar_account', 407: 'kavenegar_account',
    416: 'kavenegar_account', 427: 'kavenegar_account', 429: 'kavenegar_account',
    418: 'insufficient_credit',
    411: 'wrong_number_format',
    412: 'kavenegar_sender',
    413: 'kavenegar_content', 420: 'kavenegar_content', 422: 'kavenegar_content',
}
# Per-message status in a send answer that is already a failure.
ENTRY_TO_STATE = {6: 'not_delivered', 11: 'not_delivered', 13: 'not_delivered', 14: 'rejected'}


def local_id(sms_uuid):
    """Kavenegar refuses to send a local id twice, which makes a retry after a
    timeout safe. It is derived from the SMS uuid rather than from the record id,
    so a test database sharing the API key can never shadow a production SMS."""
    return int(sms_uuid[:15], 16)


class SmsApiKavenegar(SmsApiBase):
    PROVIDER_TO_SMS_FAILURE_TYPE = SmsApiBase.PROVIDER_TO_SMS_FAILURE_TYPE | {
        'insufficient_credit': 'sms_credit',
        'kavenegar_account': 'kavenegar_account',
        'kavenegar_sender': 'kavenegar_sender',
        'kavenegar_content': 'kavenegar_content',
    }

    def _client(self):
        company = (self.company or self.env.company).sudo()
        return company, company._sms_kavenegar_client()

    def _send_sms_batch(self, messages, delivery_reports_url=False):
        company, client = self._client()
        errors = self._get_sms_api_error_messages()
        flat = [(number['uuid'], number['number'], message.get('content') or '')
                for message in messages for number in message.get('numbers') or []]
        results = []
        for start in range(0, len(flat), kavenegar.SEND_LIMIT):
            chunk = flat[start:start + kavenegar.SEND_LIMIT]
            if not company.sms_kavenegar_sender:
                results += [{'uuid': uuid, 'state': 'kavenegar_sender',
                             'failure_reason': errors['kavenegar_sender']} for uuid, _n, _b in chunk]
                continue
            try:
                entries = client.send_array(
                    [number for _u, number, _b in chunk],
                    [company.sms_kavenegar_sender] * len(chunk),
                    [body for _u, _n, body in chunk],
                    [local_id(uuid) for uuid, _n, _b in chunk],
                ) or []
            except KavenegarError as e:
                state = RETURN_TO_STATE.get(e.status, 'server_error')
                _logger.warning("Kavenegar: %s for %s SMS", e, len(chunk))
                results += [{'uuid': uuid, 'state': state, 'failure_reason': e.message or errors.get(state)}
                            for uuid, _n, _b in chunk]
                continue
            results += self._match_entries(chunk, entries)
        return results

    def _match_entries(self, chunk, entries):
        """Kavenegar answers in the order it was asked; the receptor is checked too,
        and an SMS with no matching entry is reported, not assumed sent."""
        by_tail = {}
        for entry in entries:
            by_tail.setdefault(str(entry.get('receptor') or '')[-10:], []).append(entry)
        results = []
        for position, (uuid, number, _body) in enumerate(chunk):
            tail = ''.join(c for c in number if c.isdigit())[-10:]
            entry = entries[position] if position < len(entries) else None
            if not entry or str(entry.get('receptor') or '')[-10:] != tail:
                entry = (by_tail.get(tail) or [None]).pop(0) if by_tail.get(tail) else None
            if not entry:
                results.append({'uuid': uuid, 'state': 'server_error',
                                'failure_reason': _("Kavenegar did not return this message.")})
                continue
            status = int(entry.get('status') or 0)
            state = ENTRY_TO_STATE.get(status)
            results.append({
                'uuid': uuid,
                'state': state or 'success',
                'failure_reason': entry.get('statustext') if state else False,
                'kavenegar_messageid': str(entry.get('messageid') or ''),
                'kavenegar_status': status,
            })
        return results

    def _get_sms_api_error_messages(self):
        error_dict = super()._get_sms_api_error_messages()
        error_dict.update({
            'kavenegar_account': _("Kavenegar refused the API key or this server's address."),
            'kavenegar_sender': _("The Kavenegar sender line is missing or not yours."),
            'kavenegar_content': _("Kavenegar refused the text: empty, too long, or containing a link."),
            'insufficient_credit': _("The Kavenegar account has no credit left."),
            'wrong_number_format': _("The number you're trying to reach is not correctly formatted."),
            'server_error': _("Kavenegar could not be reached, or asked to retry later."),
            'unknown': _("Unknown Kavenegar error."),
        })
        return error_dict
