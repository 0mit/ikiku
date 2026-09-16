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
from odoo.exceptions import ValidationError

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
    matched_partner_id = fields.Many2one(
        'res.partner', string="حسابی با همین شماره", compute='_compute_matched_partner_id', compute_sudo=True,
        help="حسابی که همین شماره شمارهٔ ورودش است، تا همکار پیش از زنگ زدن بداند با کی حرف می‌زند.")
    matched_partner_state = fields.Selection(
        [('proven', "تأییدشده با کدِ پیامک"), ('staff', "نوشتهٔ همکار، هنوز تأییدنشده"), ('unproven', "تأییدنشده")],
        string="وضعِ شماره", compute='_compute_matched_partner_id', compute_sudo=True)

    state = fields.Selection([
        ('new', "تازه"), ('called', "زنگ زدیم"), ('closed', "بسته شد"),
    ], string="وضعیت", default='new', required=True, tracking=True)

    @api.depends('mobile')
    def _compute_matched_partner_id(self):
        Partner = self.env['res.partner'].sudo().with_context(active_test=False)
        for request in self:
            try:
                mobile = Partner.normalise_mobile(request.mobile)
            except ValidationError:
                mobile = False
            partner = Partner.search([('ikiku_mobile', '=', mobile)], limit=1) if mobile else Partner
            request.matched_partner_id = partner
            request.matched_partner_state = partner.ikiku_mobile_state if partner else False

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
