# Part of iKiKu. Licensed under AGPL-3.0.
from odoo import fields, models

SMSIR_FAILURE_TYPES = [
    ('smsir_account', 'sms.ir: API key, account or address refused'),
    ('smsir_sender', 'sms.ir: sender line'),
    ('smsir_content', 'sms.ir: text refused'),
    ('smsir_unconfirmed', 'sms.ir: may have been sent, not confirmed'),
]


class MailNotification(models.Model):
    _inherit = 'mail.notification'

    failure_type = fields.Selection(selection_add=SMSIR_FAILURE_TYPES)
