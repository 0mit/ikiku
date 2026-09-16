# Part of iKiKu. Licensed under AGPL-3.0.
"""«می‌خوام یکی کمکم کنه»: a call-back request (operator, 2026-09-16, D-6 D).

A person who is stuck leaves a number and a time of day; a staff member calls back
from the co-op's stated number. A published support line comes later. No SMS is sent
for a request, so it costs nothing and cannot drain the SMS credit.

The number is the person's contact, restricted like every phone number (بند ۷): only
staff read these records, and the page never shows one back.
"""
from datetime import timedelta

from odoo import api, fields, models

MAX_PER_NUMBER_PER_DAY = 3


class IkikuHelpRequest(models.Model):
    _name = 'ikiku.help.request'
    _description = "درخواستِ تماس"
    _inherit = ['mail.thread']
    _order = 'state, create_date desc'

    name = fields.Char("نام", required=True)
    mobile = fields.Char("شماره", required=True)
    best_time = fields.Selection([
        ('morning', "صبح"), ('noon', "ظهر"), ('evening', "عصر"),
    ], string="کِی زنگ بزنیم", required=True, default='morning')
    topic = fields.Text("کجا گیر کرده")
    from_page = fields.Char("از صفحه‌ی")
    partner_id = fields.Many2one('res.partner', string="حساب", readonly=True)
    state = fields.Selection([
        ('new', "تازه"), ('called', "زنگ زدیم"), ('closed', "بسته شد"),
    ], string="وضعیت", default='new', required=True, tracking=True)

    @api.model
    def too_many(self, mobile):
        return self.sudo().search_count([
            ('mobile', '=', mobile),
            ('create_date', '>=', fields.Datetime.now() - timedelta(days=1)),
        ]) >= MAX_PER_NUMBER_PER_DAY

    def action_called(self):
        self.write({'state': 'called'})

    def action_close(self):
        self.write({'state': 'closed'})
