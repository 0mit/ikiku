# Part of iKiKu. Licensed under AGPL-3.0.
"""Odoo's SMS provider interface, answered by sms.ir.

The contract is sms_kavenegar's: `_send_sms_batch` returns one result per SMS,
{'uuid', 'state', 'failure_reason'}, here with sms.ir's message and pack ids
added for the tracker.

A result sms.ir may have acted on is never reported as a plain failure. It is
'smsir_unconfirmed', whose message says to look in the panel before resending,
because sms.ir would send a resent SMS a second time.
"""
import logging

from odoo import _
from odoo.addons.sms.tools.sms_api import SmsApiBase

from . import smsir
from .smsir import SmsIrError, local_mobile

_logger = logging.getLogger(__name__)

# sms.ir status for a whole request -> the state given to every SMS in it.
RETURN_TO_STATE = {
    10: 'smsir_account', 11: 'smsir_account', 12: 'smsir_account',
    13: 'smsir_account', 14: 'smsir_account', 15: 'smsir_account',
    101: 'smsir_sender',
    102: 'insufficient_credit',
    103: 'smsir_content',
    104: 'wrong_number_format',
    115: 'rejected',
}


class SmsApiSmsIr(SmsApiBase):
    PROVIDER_TO_SMS_FAILURE_TYPE = SmsApiBase.PROVIDER_TO_SMS_FAILURE_TYPE | {
        'insufficient_credit': 'sms_credit',
        'smsir_account': 'smsir_account',
        'smsir_sender': 'smsir_sender',
        'smsir_content': 'smsir_content',
        'smsir_unconfirmed': 'smsir_unconfirmed',
    }

    def _send_sms_batch(self, messages, delivery_reports_url=False):
        company = (self.company or self.env.company).sudo()
        client = company._sms_smsir_client()
        errors = self._get_sms_api_error_messages()
        flat = [(number['uuid'], number['number'], message.get('content') or '')
                for message in messages for number in message.get('numbers') or []]
        results = []
        for start in range(0, len(flat), smsir.SEND_LIMIT):
            chunk = flat[start:start + smsir.SEND_LIMIT]
            if not company.sms_smsir_line:
                results += self._fail(chunk, 'smsir_sender', errors['smsir_sender'])
                continue
            try:
                data = client.send_like_to_like(
                    company.sms_smsir_line,
                    [local_mobile(number) for _u, number, _b in chunk],
                    [body for _u, _n, body in chunk],
                )
            except SmsIrError as e:
                _logger.warning("sms.ir: %s for %s SMS", e, len(chunk))
                if e.status == 0:
                    state = 'smsir_unconfirmed' if e.maybe_sent else 'server_error'
                    results += self._fail(chunk, state, errors[state])
                else:
                    state = RETURN_TO_STATE.get(e.status, 'server_error')
                    results += self._fail(chunk, state, e.message or errors.get(state))
                continue
            results += self._match_ids(chunk, data, errors)
        return results

    @staticmethod
    def _fail(chunk, state, reason):
        return [{'uuid': uuid, 'state': state, 'failure_reason': reason} for uuid, _n, _b in chunk]

    def _match_ids(self, chunk, data, errors):
        """sms.ir answers with one id per mobile, in the order asked: null for a
        number it refused, 0 for one on its blacklist. The ids carry no number to
        match them by, so an answer of the wrong length is not guessed at."""
        ids = data.get('messageIds') if isinstance(data, dict) else None
        if not isinstance(ids, list) or len(ids) != len(chunk):
            _logger.warning("sms.ir: accepted %s SMS but answered %r", len(chunk), data)
            return self._fail(chunk, 'smsir_unconfirmed', errors['smsir_unconfirmed'])
        pack_id = str(data.get('packId') or '')
        results = []
        for (uuid, _number, _body), message_id in zip(chunk, ids):
            if message_id is None:
                results.append({'uuid': uuid, 'state': 'wrong_number_format',
                                'failure_reason': errors['wrong_number_format']})
            elif not message_id:
                results.append({'uuid': uuid, 'state': 'rejected', 'failure_reason': errors['rejected']})
            else:
                results.append({'uuid': uuid, 'state': 'success', 'failure_reason': False,
                                'smsir_messageid': str(message_id), 'smsir_pack_id': pack_id})
        return results

    def _get_sms_api_error_messages(self):
        error_dict = super()._get_sms_api_error_messages()
        error_dict.update({
            'smsir_account': _("sms.ir refused the API key, the account, or this server's address."),
            'smsir_sender': _("The sms.ir sender line is missing or not one of this account's lines."),
            'smsir_content': _("sms.ir refused the text."),
            'smsir_unconfirmed': _("The request reached sms.ir but no usable answer came back, so this SMS "
                                   "may have been sent. sms.ir cannot refuse a repeat: check its panel "
                                   "before sending it again."),
            'insufficient_credit': _("The sms.ir account has no credit left."),
            'wrong_number_format': _("The number you're trying to reach is not correctly formatted."),
            'rejected': _("The number is on sms.ir's blacklist."),
            'server_error': _("sms.ir could not be reached, or asked to retry later."),
            'unknown': _("Unknown sms.ir error."),
        })
        return error_dict
