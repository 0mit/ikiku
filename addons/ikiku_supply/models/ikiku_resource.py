# Part of iKiKu. Licensed under AGPL-3.0.
"""The resource: a professional, their record, and nothing about where they sleep.

iKiKu does NOT employ these people. The business they are placed with is their
employer; this co-op records, verifies and -- through the dispute procedure --
acts as their union. That is why there is no hr.employee here and no contract,
and why `ikiku.resume.line` exists instead of `hr.resume.line`, whose
`employee_id` is required and would have this database assert an employment
relationship that does not exist.
"""
from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.ikiku_base.models.jalali import format_jalali


class IkikuResource(models.Model):
    _name = 'ikiku.resource'
    _description = "نیرو"
    _inherit = ['mail.thread', 'ikiku.publishable']
    _order = 'standing desc, id desc'

    partner_id = fields.Many2one('res.partner', string="شخص", required=True,
                                 ondelete='restrict', index=True, tracking=True)
    name = fields.Char(related='partner_id.name', store=True, readonly=False, string="نام")
    slug = fields.Char("نشانیِ عمومی", copy=False, index=True,
                       help="بخشِ پایانیِ نشانیِ پروندهٔ عمومی.")
    province_id = fields.Many2one(related='partner_id.ikiku_province_id',
                                  store=True, readonly=False, string="استان")
    city = fields.Char(related='partner_id.ikiku_city', store=True, readonly=False, string="شهر")
    standing = fields.Float(related='partner_id.ikiku_standing', store=True, string="اعتبار")
    is_verified = fields.Boolean(related='partner_id.ikiku_is_verified', store=True,
                                 string="هویت تأییدشده")
    headline = fields.Char("یک خط دربارهٔ خودتان")
    bio = fields.Text("شرح")

    state = fields.Selection([
        ('draft', "پیش‌نویس"),
        ('submitted', "ثبت‌شده، در انتظار بررسی"),
        ('active', "فعال"),
        ('paused', "موقتاً غیرفعال"),
    ], default='draft', required=True, tracking=True, string="وضعیت")

    skill_ids = fields.One2many('ikiku.resource.skill', 'resource_id', string="مهارت‌ها")
    resume_line_ids = fields.One2many('ikiku.resume.line', 'resource_id', string="سابقه")
    availability_ids = fields.One2many('ikiku.availability', 'resource_id', string="در دسترس")
    assertion_ids = fields.One2many('ikiku.assertion',
                                    related='partner_id.ikiku_assertion_ids', string="ادعاها")

    supported_claim_count = fields.Integer(compute='_compute_claim_counts', store=True)
    contested_claim_count = fields.Integer(compute='_compute_claim_counts', store=True)

    _partner_uniq = models.Constraint('UNIQUE(partner_id)', "برای هر شخص یک پرونده.")
    _slug_uniq = models.Constraint('UNIQUE(slug)', "نشانیِ عمومی باید یکتا باشد.")

    @api.depends('assertion_ids.state')
    def _compute_claim_counts(self):
        for rec in self:
            rec.supported_claim_count = len(rec.assertion_ids.filtered(
                lambda a: a.state == 'supported'))
            rec.contested_claim_count = len(rec.assertion_ids.filtered(
                lambda a: a.state == 'contested'))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if not rec.slug:
                rec.slug = 'r-%d' % rec.id
        return records

    def action_submit(self):
        for rec in self:
            if not rec.skill_ids:
                raise UserError("دست‌کم یک مهارت ثبت کنید تا پرونده قابلِ بررسی باشد.")
            rec.state = 'submitted'

    def action_activate(self):
        if not self.env.user.has_group('ikiku_base.group_ikiku_staff'):
            raise UserError("فعال‌کردن پرونده به دستِ کارکنان پلتفرم انجام می‌شود.")
        self.write({'state': 'active'})

    def claim_skill(self, spec_node, level_text=None):
        """A self-claim is recorded as a self-claim. بند ۳."""
        self.ensure_one()
        return self.env['ikiku.assertion'].create({
            'resource_id': self.partner_id.id,
            'claim_kind': 'skill',
            'spec_node_id': spec_node.id,
            'value_text': level_text,
            'asserted_by_id': self.partner_id.id,
            'method': 'self',
        })


class IkikuResourceSkill(models.Model):
    """Reuses Odoo's skill catalogue and level machinery without pretending the
    person is our employee. The mixin only asks for the name of the link field."""
    _name = 'ikiku.resource.skill'
    _inherit = 'hr.individual.skill.mixin'
    _description = "مهارتِ نیرو"

    resource_id = fields.Many2one('ikiku.resource', required=True, index=True,
                                  ondelete='cascade', string="نیرو")

    def _linked_field_name(self):
        return 'resource_id'


class IkikuResumeLine(models.Model):
    _name = 'ikiku.resume.line'
    _description = "سطرِ سابقه"
    _order = 'date_start desc'

    resource_id = fields.Many2one('ikiku.resource', required=True, index=True,
                                  ondelete='cascade', string="نیرو")
    name = fields.Char("عنوان", required=True)
    line_type = fields.Selection([
        ('experience', "سابقهٔ کار"),
        ('education', "آموزش"),
        ('certification', "گواهی"),
    ], string="نوع", required=True, default='experience')
    employer_name = fields.Char("کارفرما",
                                help="نامِ کسب‌وکار. کارفرما همان کسب‌وکار است، نه ایکیکو.")
    employer_partner_id = fields.Many2one('res.partner', string="کسب‌وکارِ ثبت‌شده",
                                          help="اگر کسب‌وکار در ایکیکو هست، به آن وصل کنید "
                                               "تا بتواند این سابقه را راست‌آزمایی کند.")
    spec_node_id = fields.Many2one('ikiku.spec.node', string="گرهٔ استاندارد")
    date_start = fields.Date("از", required=True)
    date_end = fields.Date("تا")
    description = fields.Text("شرح")
    assertion_id = fields.Many2one('ikiku.assertion', string="ادعای متناظر", readonly=True)

    date_start_fa = fields.Char(compute='_compute_dates_fa', string="از (شمسی)")
    date_end_fa = fields.Char(compute='_compute_dates_fa', string="تا (شمسی)")

    @api.depends('date_start', 'date_end')
    def _compute_dates_fa(self):
        for rec in self:
            rec.date_start_fa = format_jalali(rec.date_start)
            rec.date_end_fa = format_jalali(rec.date_end) if rec.date_end else "اکنون"

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        for line in lines:
            # Every history entry becomes a claim that somebody can verify or
            # dispute. A résumé nobody can challenge is a CV, not a record.
            line.assertion_id = self.env['ikiku.assertion'].create({
                'resource_id': line.resource_id.partner_id.id,
                'claim_kind': 'experience' if line.line_type == 'experience' else 'certification',
                'spec_node_id': line.spec_node_id.id,
                'value_text': line.name,
                'date_from': line.date_start,
                'date_to': line.date_end,
                'asserted_by_id': line.resource_id.partner_id.id,
                'method': 'self',
            })
        return lines
