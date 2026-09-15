# Part of iKiKu. Licensed under AGPL-3.0.
"""Delivery status for SMS sent through sms.ir.

sms.ir documents no delivery callback, so status only comes back by polling,
one pack report per send request. How long sms.ir keeps a pack report is not
documented either; the window below is Kavenegar's, and a report that has gone
simply stops being asked for once the window closes.
"""
import logging
from datetime import timedelta

from odoo import api, fields, models

from odoo.addons.sms_smsir.tools import smsir
from odoo.addons.sms_smsir.tools.smsir import SmsIrError

_logger = logging.getLogger(__name__)

STATUS_WINDOW = timedelta(hours=48)
# Statuses after which asking again about another pack is pointless this round.
STOP_POLLING = {0, 10, 11, 12, 13, 14, 15, 20}


class SmsTracker(models.Model):
    _inherit = 'sms.tracker'

    smsir_messageid = fields.Char("sms.ir message id", readonly=True, index='btree_not_null')
    smsir_pack_id = fields.Char("sms.ir pack id", readonly=True)
    smsir_state = fields.Integer("sms.ir delivery state", readonly=True)
    smsir_company_id = fields.Many2one('res.company', readonly=True)
    smsir_sent_at = fields.Datetime(readonly=True)

    def _smsir_apply_state(self, state):
        for tracker in self:
            if tracker.smsir_state == state:
                continue
            tracker.smsir_state = state
            if state == smsir.STATE_DELIVERED:
                tracker._action_update_from_sms_state('sent')
            elif state in smsir.STATE_FAILED:
                tracker._action_update_from_provider_error('not_delivered')
            elif state == smsir.STATE_BLACKLISTED:
                tracker._action_update_from_provider_error('rejected')
            elif state in smsir.STATE_AT_OPERATOR:
                tracker._action_update_from_sms_state('pending')

    @api.model
    def _smsir_poll_status(self):
        pending = self.search([
            ('smsir_pack_id', '!=', False),
            ('smsir_state', 'not in', list(smsir.STATE_FINAL)),
            ('smsir_sent_at', '>=', fields.Datetime.now() - STATUS_WINDOW),
        ])
        for company, trackers in pending.grouped('smsir_company_id').items():
            if not company.sms_smsir_enabled:
                continue
            client = company._sms_smsir_client()
            for pack_id, pack in trackers.grouped('smsir_pack_id').items():
                try:
                    entries = client.pack_report(pack_id)
                except SmsIrError as e:
                    if e.status in STOP_POLLING:
                        break
                    continue
                if not isinstance(entries, list):
                    _logger.warning("sms.ir: pack report %s is not a list of messages: %r", pack_id, entries)
                    continue
                by_id = pack.grouped('smsir_messageid')
                for entry in entries:
                    found = by_id.get(str((entry or {}).get('messageId')))
                    if found and entry.get('deliveryState') is not None:
                        found._smsir_apply_state(int(entry['deliveryState']))
