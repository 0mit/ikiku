# Part of iKiKu. Licensed under AGPL-3.0.
"""The verification ledger: assertions and verdicts, never a bare star.

بند ۳ -- every claim names who said it, when, and how they know.
بند ۴ -- no claim about a person is final until that person has been heard, so
         every assertion carries a route to a dispute from the day it is written.

Anti-Sybil without banning anyone: a verification's weight is the verifier's own
standing FROZEN AT THE MOMENT they spoke. Two accounts that only verify each
other converge toward zero weight, and the rule fits in one public sentence.
Freezing also removes the recursion -- strength never has to re-read a graph.
"""
from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

METHODS = [
    ('self', "خودِ فرد"),
    ('coworker', "هم‌کار"),
    ('employer', "کارفرما"),
    ('academy', "آموزشگاه"),
    ('platform', "پلتفرم"),
    ('document', "سند"),
]

# What a method is worth before the verifier's own standing is applied.
METHOD_BASE = {
    'self': 0.0,        # a self-claim is a claim, not evidence
    'coworker': 1.0,
    'employer': 1.5,
    'academy': 2.0,
    'platform': 1.0,
    'document': 1.0,
}


class IkikuAssertion(models.Model):
    _name = 'ikiku.assertion'
    _description = "ادعا"
    _order = 'create_date desc'
    _inherit = ['mail.thread']

    name = fields.Char(compute='_compute_name', store=True)
    resource_id = fields.Many2one('res.partner', string="دربارهٔ", required=True,
                                  ondelete='cascade', index=True)
    claim_kind = fields.Selection([
        ('skill', "مهارت"),
        ('experience', "سابقه"),
        ('certification', "گواهی"),
        ('attribute', "ویژگی"),
    ], string="نوعِ ادعا", required=True, default='skill')
    spec_node_id = fields.Many2one('ikiku.spec.node', string="گرهٔ استاندارد", index=True)
    value_text = fields.Char("مقدار")
    date_from = fields.Date("از")
    date_to = fields.Date("تا")

    asserted_by_id = fields.Many2one('res.partner', string="گویندهٔ ادعا", required=True,
                                     default=lambda self: self.env.user.partner_id)
    method = fields.Selection(METHODS, string="از چه راه", required=True, default='self')
    asserted_on = fields.Date("تاریخِ ادعا", required=True,
                              default=fields.Date.context_today)

    verification_ids = fields.One2many('ikiku.verification', 'assertion_id', string="راست‌آزمایی‌ها")
    confirm_count = fields.Integer(compute='_compute_strength', store=True)
    dispute_count = fields.Integer(compute='_compute_strength', store=True)
    strength = fields.Float("استحکام", compute='_compute_strength', store=True,
                            help="از راست‌آزمایی‌ها به دست می‌آید. عددِ ذخیره‌شده‌ای "
                                 "نیست که کسی بتواند دستکاری کند.")
    dispute_id = fields.Many2one('ikiku.dispute', string="پرونده", readonly=True,
                                 help="بند ۴: هر ادعا از روزِ نخست راهی به دفاع دارد.")
    state = fields.Selection([
        ('claimed', "ادعا شده"),
        ('supported', "پشتیبانی‌شده"),
        ('contested', "مورد اعتراض"),
        ('withdrawn', "پس‌گرفته"),
    ], default='claimed', required=True, tracking=True, string="وضعیت")

    @api.depends('resource_id', 'spec_node_id', 'value_text', 'claim_kind')
    def _compute_name(self):
        for rec in self:
            subject = rec.spec_node_id.name or rec.value_text or ''
            rec.name = "%s — %s" % (rec.resource_id.display_name or '', subject)

    @api.depends('verification_ids.verdict', 'verification_ids.weight')
    def _compute_strength(self):
        for rec in self:
            confirms = rec.verification_ids.filtered(lambda v: v.verdict == 'confirm')
            disputes = rec.verification_ids.filtered(lambda v: v.verdict == 'dispute')
            rec.confirm_count = len(confirms)
            rec.dispute_count = len(disputes)
            base = METHOD_BASE.get(rec.method, 0.0)
            rec.strength = base + sum(confirms.mapped('weight')) - sum(disputes.mapped('weight'))
            if rec.state not in ('withdrawn',):
                if disputes:
                    rec.state = 'contested'
                elif confirms:
                    rec.state = 'supported'

    @api.constrains('asserted_by_id', 'method')
    def _check_self_claim_honest(self):
        for rec in self:
            is_self = rec.asserted_by_id == rec.resource_id
            if is_self and rec.method != 'self':
                raise ValidationError(
                    "ادعایی که خودِ فرد دربارهٔ خودش می‌گوید باید «خودِ فرد» ثبت شود. "
                    "بند ۳: هر ادعا صاحبِ راستینش را نشان می‌دهد.")

    def action_open_dispute(self, respondent=None, ground=''):
        self.ensure_one()
        if self.dispute_id:
            return self.dispute_id
        dispute = self.env['ikiku.dispute'].create({
            'assertion_id': self.id,
            'opener_id': self.env.user.partner_id.id,
            'respondent_id': (respondent or self.asserted_by_id).id,
            'ground': ground,
        })
        self.dispute_id = dispute
        return dispute


class IkikuVerification(models.Model):
    _name = 'ikiku.verification'
    _description = "راست‌آزمایی"
    _order = 'create_date desc'

    assertion_id = fields.Many2one('ikiku.assertion', required=True, ondelete='cascade',
                                   index=True, string="ادعا")
    verifier_id = fields.Many2one('res.partner', string="راست‌آزما", required=True,
                                  default=lambda self: self.env.user.partner_id)
    verdict = fields.Selection([
        ('confirm', "تأیید می‌کنم"),
        ('dispute', "رد می‌کنم"),
        ('cannot_say', "نمی‌دانم"),
    ], string="رأی", required=True)
    evidence = fields.Text("شاهد", help="چگونه می‌دانید؟")
    verified_on = fields.Date("تاریخ", required=True, default=fields.Date.context_today)
    verifier_standing = fields.Float(
        "اعتبارِ راست‌آزما در همان لحظه", readonly=True,
        help="در لحظهٔ ثبت منجمد می‌شود. اگر بعداً اعتبارِ او تغییر کند، "
             "این رأی تغییر نمی‌کند — چون در آن لحظه گفته شده.")
    weight = fields.Float("وزن", compute='_compute_weight', store=True)
    is_public = fields.Boolean("عمومی", default=True)

    _one_verdict_per_verifier = models.Constraint(
        'UNIQUE(assertion_id, verifier_id)',
        "هر کس دربارهٔ هر ادعا فقط یک رأی دارد.")

    @api.depends('verifier_standing', 'verdict')
    def _compute_weight(self):
        for rec in self:
            rec.weight = 0.0 if rec.verdict == 'cannot_say' else max(rec.verifier_standing, 0.0)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            partner = self.env['res.partner'].browse(vals.get('verifier_id'))
            vals.setdefault('verifier_standing', partner.ikiku_standing)
        return super().create(vals_list)

    @api.constrains('verifier_id', 'assertion_id')
    def _check_not_self_verified(self):
        for rec in self:
            if rec.verifier_id == rec.assertion_id.resource_id:
                raise ValidationError("کسی نمی‌تواند ادعای دربارهٔ خودش را راست‌آزمایی کند.")


class IkikuDispute(models.Model):
    _name = 'ikiku.dispute'
    _description = "پرونده"
    _order = 'create_date desc'
    _inherit = ['mail.thread']

    name = fields.Char(compute='_compute_name', store=True)
    assertion_id = fields.Many2one('ikiku.assertion', string="ادعا", ondelete='cascade')
    opener_id = fields.Many2one('res.partner', string="شاکی", required=True)
    respondent_id = fields.Many2one('res.partner', string="طرفِ مقابل", required=True)
    ground = fields.Text("موضوع")
    opener_statement = fields.Text("گفتهٔ شاکی")
    respondent_statement = fields.Text("گفتهٔ طرفِ مقابل")
    state = fields.Selection([
        ('open', "باز"),
        ('heard', "هر دو طرف شنیده شدند"),
        ('ruled', "رأی صادر شد"),
    ], default='open', required=True, tracking=True, string="وضعیت")
    ruling = fields.Text("رأی")
    ruled_on = fields.Date("تاریخِ رأی")
    is_public = fields.Boolean("عمومی", default=True,
                               help="بند ۴: نتیجه را همه می‌بینند.")

    @api.depends('opener_id', 'respondent_id')
    def _compute_name(self):
        for rec in self:
            rec.name = "%s ← %s" % (rec.opener_id.display_name or '',
                                    rec.respondent_id.display_name or '')

    def action_rule(self, ruling):
        """A ruling is refused until BOTH sides are on the record. بند ۴."""
        self.ensure_one()
        if not (self.opener_statement and self.respondent_statement):
            raise UserError(
                "تا وقتی هر دو طرف گفته‌شان را ثبت نکرده‌اند، رأیی صادر نمی‌شود. "
                "این بندِ ۴ مرام‌نامه است و دور زدنش ممکن نیست.")
        self.write({'state': 'ruled', 'ruling': ruling,
                    'ruled_on': fields.Date.context_today(self)})
        return True
