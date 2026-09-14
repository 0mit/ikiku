# Part of iKiKu. Licensed under AGPL-3.0.
from datetime import datetime, timezone

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.sms_kavenegar.tools.kavenegar import KavenegarError


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    sms_kavenegar_enabled = fields.Boolean(related='company_id.sms_kavenegar_enabled', readonly=False)
    sms_kavenegar_api_key = fields.Char(related='company_id.sms_kavenegar_api_key', readonly=False)
    sms_kavenegar_sender = fields.Char(related='company_id.sms_kavenegar_sender', readonly=False)
    sms_kavenegar_otp_template = fields.Char(related='company_id.sms_kavenegar_otp_template', readonly=False)
    sms_kavenegar_callback_url = fields.Char("Delivery callback URL", compute='_compute_sms_kavenegar_callback_url')
    sms_kavenegar_test_number = fields.Char("Test number")

    @api.depends('company_id')
    def _compute_sms_kavenegar_callback_url(self):
        for settings in self:
            settings.sms_kavenegar_callback_url = settings.company_id._sms_kavenegar_callback_url()

    def action_sms_kavenegar_check_account(self):
        try:
            info = self.company_id._sms_kavenegar_client().account_info() or {}
        except KavenegarError as e:
            return self._sms_kavenegar_notify('danger', _("Kavenegar answered %(status)s: %(message)s",
                                                          status=e.status, message=e.message))
        expires = info.get('expiredate')
        expires = datetime.fromtimestamp(int(expires), tz=timezone.utc).date() if expires else '-'
        return self._sms_kavenegar_notify('success', _("Credit: %(credit)s rials, account valid until %(date)s.",
                                                       credit=info.get('remaincredit'), date=expires))

    def action_sms_kavenegar_send_test(self):
        if not self.sms_kavenegar_test_number:
            raise UserError(_("Enter the number to send a test SMS to."))
        composer = self.env['sms.composer'].create({
            'body': _("Test SMS from %s through Kavenegar.", self.company_id.name),
            'composition_mode': 'numbers',
            'numbers': self.sms_kavenegar_test_number,
        })
        sms = composer._action_send_sms()[:1]
        if sms.state in ('pending', 'sent', 'process') or not sms.exists():
            return self._sms_kavenegar_notify('success', _("Kavenegar accepted the test SMS."))
        messages = self.company_id._get_sms_api_class()(self.env)._get_sms_api_error_messages()
        return self._sms_kavenegar_notify('danger', messages.get(sms.failure_type) or sms.failure_type or _("Not sent."))

    def _sms_kavenegar_notify(self, kind, message):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': _("Kavenegar SMS"), 'message': message, 'type': kind, 'sticky': kind == 'danger'},
        }
