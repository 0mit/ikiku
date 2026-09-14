# Part of iKiKu. Licensed under AGPL-3.0.
"""Kavenegar's delivery callback.

Configured per line in the Kavenegar panel, it sends `messageid` and `status`
and nothing that proves who sent them. The secret token in the path is the
proof. Kavenegar retries a non-200 answer every 2 minutes, 30 times, so a
well-formed call about a message this database does not know still gets 200.
"""
import logging
import re

from odoo.http import Controller, request, route

_logger = logging.getLogger(__name__)
TOKEN_RE = re.compile(r'^[0-9a-f]{32}$')


class SmsKavenegarController(Controller):

    @route('/sms_kavenegar/status/<string:token>', type='http', auth='public',
           methods=['GET', 'POST'], csrf=False, save_session=False)
    def status(self, token, messageid=None, status=None, **kwargs):
        if not TOKEN_RE.match(token or ''):
            raise request.not_found()
        company = request.env['res.company'].sudo().search(
            [('sms_kavenegar_callback_token', '=', token), ('sms_kavenegar_enabled', '=', True)], limit=1)
        if not company:
            raise request.not_found()
        try:
            message_id, status_code = int(messageid), int(status)
        except (TypeError, ValueError):
            _logger.warning("Kavenegar callback without a usable messageid/status")
            return request.make_response('OK')
        trackers = request.env['sms.tracker'].sudo().search(
            [('kavenegar_messageid', '=', str(message_id))])
        trackers._kavenegar_apply_status(status_code)
        return request.make_response('OK')
