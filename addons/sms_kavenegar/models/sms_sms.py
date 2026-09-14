# Part of iKiKu. Licensed under AGPL-3.0.
from odoo import fields, models

from odoo.addons.sms_kavenegar.models.mail_notification import KAVENEGAR_FAILURE_TYPES
from odoo.addons.sms_kavenegar.tools.sms_api import SmsApiKavenegar


class SmsSms(models.Model):
    _inherit = 'sms.sms'

    failure_type = fields.Selection(selection_add=KAVENEGAR_FAILURE_TYPES)

    def _split_by_api(self):
        """The base yields the IAP API for every SMS, whatever the company says;
        SMS of a company sending through Kavenegar go there instead."""
        via_base = self.browse()
        for company, company_sms in self.grouped(lambda sms: sms._get_sms_company()).items():
            if company.sms_kavenegar_enabled:
                sms_api = SmsApiKavenegar(self.env)
                sms_api._set_company(company)
                yield sms_api, company_sms
            else:
                via_base |= company_sms
        if via_base:
            yield from super(SmsSms, via_base)._split_by_api()

    def _handle_call_result_hook(self, results):
        """The SMS is deleted once sent; its tracker keeps Kavenegar's message id so
        the callback and the polling job can still find it."""
        by_uuid = self.grouped('uuid')
        now = fields.Datetime.now()
        for result in results:
            sms = by_uuid.get(result.get('uuid'))
            if result.get('kavenegar_messageid') and sms and sms.sms_tracker_id:
                sms.sms_tracker_id.write({
                    'kavenegar_messageid': result['kavenegar_messageid'],
                    'kavenegar_status': result.get('kavenegar_status') or 0,
                    'kavenegar_company_id': sms._get_sms_company().id,
                    'kavenegar_sent_at': now,
                })
        super()._handle_call_result_hook(results)
