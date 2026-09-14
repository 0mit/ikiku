# Part of iKiKu. Licensed under AGPL-3.0.
from odoo import fields, models

KAVENEGAR_FAILURE_TYPES = [
    ('kavenegar_account', 'Kavenegar: API key or address refused'),
    ('kavenegar_sender', 'Kavenegar: sender line'),
    ('kavenegar_content', 'Kavenegar: text refused'),
]


class MailNotification(models.Model):
    _inherit = 'mail.notification'

    failure_type = fields.Selection(selection_add=KAVENEGAR_FAILURE_TYPES)
