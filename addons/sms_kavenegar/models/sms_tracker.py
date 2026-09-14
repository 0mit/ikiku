# Part of iKiKu. Licensed under AGPL-3.0.
"""Delivery status for SMS sent through Kavenegar.

The sms.sms record is deleted once sent, so Kavenegar's message id lives on the
tracker, which is what carries status to the notification. Both the callback and
the polling job end in `_kavenegar_apply_status`.
"""
from datetime import timedelta

from odoo import api, fields, models

from odoo.addons.sms_kavenegar.tools import kavenegar
from odoo.addons.sms_kavenegar.tools.kavenegar import KavenegarError

# Kavenegar answers sms/status only for messages of the last 48 hours.
STATUS_WINDOW = timedelta(hours=48)


class SmsTracker(models.Model):
    _inherit = 'sms.tracker'

    kavenegar_messageid = fields.Char("Kavenegar message id", readonly=True, index='btree_not_null')
    kavenegar_status = fields.Integer("Kavenegar status", readonly=True)
    kavenegar_company_id = fields.Many2one('res.company', readonly=True)
    kavenegar_sent_at = fields.Datetime(readonly=True)

    def _kavenegar_apply_status(self, status):
        for tracker in self:
            tracker.kavenegar_status = status
            if status == kavenegar.STATUS_DELIVERED:
                tracker._action_update_from_sms_state('sent')
            elif status in kavenegar.STATUS_FAILED:
                tracker._action_update_from_provider_error('not_delivered')
            elif status == kavenegar.STATUS_BLOCKED:
                tracker._action_update_from_provider_error('rejected')
            elif status in kavenegar.STATUS_AT_OPERATOR:
                tracker._action_update_from_sms_state('pending')

    @api.model
    def _kavenegar_poll_status(self):
        pending = self.search([
            ('kavenegar_messageid', '!=', False),
            ('kavenegar_status', 'not in', list(kavenegar.STATUS_FINAL)),
            ('kavenegar_sent_at', '>=', fields.Datetime.now() - STATUS_WINDOW),
        ])
        for company, trackers in pending.grouped('kavenegar_company_id').items():
            if not company.sms_kavenegar_enabled:
                continue
            client = company._sms_kavenegar_client()
            by_id = trackers.grouped('kavenegar_messageid')
            ids = list(by_id)
            for start in range(0, len(ids), kavenegar.STATUS_LIMIT):
                try:
                    entries = client.status(ids[start:start + kavenegar.STATUS_LIMIT]) or []
                except KavenegarError:
                    break
                for entry in entries:
                    found = by_id.get(str(entry.get('messageid')))
                    if found:
                        found._kavenegar_apply_status(int(entry.get('status') or 0))
