# Part of iKiKu. Licensed under AGPL-3.0.
"""Account emails wait in the mail queue, not in the visitor's request.

auth_signup sends the "account created" and set-password emails with
force_send, so the POST that creates the account holds the visitor until the
SMTP conversation ends. On 2026-09-13 both real signups hung 60-76 s on a TLS
handshake to the mail host that never completed: the button spun, and the
account was already committed underneath it. Queued, the request returns as
soon as the account exists, and the mail cron is triggered to send it at once.
"""
from odoo import models

QUEUED_TEMPLATES = (
    'auth_signup.mail_template_user_signup_account_created',
    'auth_signup.set_password_email',
    'auth_signup.portal_set_password_email',
)


class MailTemplate(models.Model):
    _inherit = 'mail.template'

    def send_mail_batch(self, res_ids, force_send=False, raise_exception=False, email_values=None,
                        email_layout_xmlid=False):
        self.ensure_one()
        if force_send and self.get_external_id().get(self.id) in QUEUED_TEMPLATES:
            force_send = False
            cron = self.env.ref('mail.ir_cron_mail_scheduler_action', raise_if_not_found=False)
            if cron:
                cron.sudo()._trigger()
        return super().send_mail_batch(res_ids, force_send=force_send, raise_exception=raise_exception,
                                       email_values=email_values, email_layout_xmlid=email_layout_xmlid)
