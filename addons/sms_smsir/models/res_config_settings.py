# Part of iKiKu. Licensed under AGPL-3.0.
from odoo import _, fields, models
from odoo.exceptions import UserError

from odoo.addons.sms_smsir.tools.smsir import SmsIrError


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    sms_smsir_enabled = fields.Boolean(related='company_id.sms_smsir_enabled', readonly=False)
    sms_smsir_api_key = fields.Char(related='company_id.sms_smsir_api_key', readonly=False)
    sms_smsir_line = fields.Char(related='company_id.sms_smsir_line', readonly=False)
    sms_smsir_otp_template_id = fields.Integer(related='company_id.sms_smsir_otp_template_id', readonly=False)
    sms_smsir_otp_parameter = fields.Char(related='company_id.sms_smsir_otp_parameter', readonly=False)
    sms_smsir_test_number = fields.Char("sms.ir test number")

    def action_sms_smsir_check_account(self):
        client = self.company_id._sms_smsir_client()
        try:
            credit = client.credit()
            lines = [str(line) for line in client.lines() or []]
        except SmsIrError as e:
            return self._sms_smsir_notify('danger', _("sms.ir answered %(status)s: %(message)s",
                                                      status=e.status, message=e.message))
        line = (self.company_id.sms_smsir_line or '').strip()
        if line and line not in lines:
            return self._sms_smsir_notify('warning', _(
                "Credit: %(credit)s. The sender line %(line)s is not one of this account's lines: %(lines)s.",
                credit=credit, line=line, lines=', '.join(lines) or '-'))
        return self._sms_smsir_notify('success', _("Credit: %(credit)s. Lines: %(lines)s.",
                                                   credit=credit, lines=', '.join(lines) or '-'))

    def action_sms_smsir_send_test(self):
        if not self.sms_smsir_test_number:
            raise UserError(_("Enter the number to send a test SMS to."))
        composer = self.env['sms.composer'].create({
            'body': _("Test SMS from %s through sms.ir.", self.company_id.name),
            'composition_mode': 'numbers',
            'numbers': self.sms_smsir_test_number,
        })
        sms = composer._action_send_sms()[:1]
        if sms.state in ('pending', 'sent', 'process') or not sms.exists():
            return self._sms_smsir_notify('success', _("sms.ir accepted the test SMS."))
        messages = self.company_id._get_sms_api_class()(self.env)._get_sms_api_error_messages()
        return self._sms_smsir_notify('danger', messages.get(sms.failure_type) or sms.failure_type or _("Not sent."))

    def _sms_smsir_notify(self, kind, message):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': _("sms.ir SMS"), 'message': message, 'type': kind, 'sticky': kind == 'danger'},
        }
