# Part of iKiKu. Licensed under AGPL-3.0.
from odoo import fields, models

from odoo.addons.sms_smsir.models.mail_notification import SMSIR_FAILURE_TYPES
from odoo.addons.sms_smsir.tools.sms_api import SmsApiSmsIr


class SmsSms(models.Model):
    _inherit = 'sms.sms'

    failure_type = fields.Selection(selection_add=SMSIR_FAILURE_TYPES)

    def _split_by_api(self):
        """The base yields the IAP API for every SMS, whatever the company says;
        SMS of a company sending through sms.ir go there instead."""
        via_base = self.browse()
        for company, company_sms in self.grouped(lambda sms: sms._get_sms_company()).items():
            if company.sms_smsir_enabled:
                sms_api = SmsApiSmsIr(self.env)
                sms_api._set_company(company)
                yield sms_api, company_sms
            else:
                via_base |= company_sms
        if via_base:
            yield from super(SmsSms, via_base)._split_by_api()

    def _handle_call_result_hook(self, results):
        """The SMS is deleted once sent; its tracker keeps sms.ir's message and pack
        ids so the polling job can still find it."""
        by_uuid = self.grouped('uuid')
        now = fields.Datetime.now()
        for result in results:
            sms = by_uuid.get(result.get('uuid'))
            if result.get('smsir_messageid') and sms and sms.sms_tracker_id:
                sms.sms_tracker_id.write({
                    'smsir_messageid': result['smsir_messageid'],
                    'smsir_pack_id': result.get('smsir_pack_id') or False,
                    'smsir_state': 0,
                    'smsir_company_id': sms._get_sms_company().id,
                    'smsir_sent_at': now,
                })
        super()._handle_call_result_hook(results)
