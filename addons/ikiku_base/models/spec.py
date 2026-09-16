# Part of iKiKu. Licensed under AGPL-3.0.
"""The spine: one standard tree, per-business overlays, and a promotion path.

A new sector is a subtree of DATA, not a new module. Nothing in this file names
a competency, a protocol or a job -- those live in `ikiku.spec.node` rows, loaded from
ikiku_base/data/ikiku.spec.node.csv. A role (the work people offer and ask for) and a
competency (a skill) are different kinds; which skills a role needs, and which fields of
knowledge a node rests on, are rows of knowledge.py.

The three states, and why each exists:
  node       the standard. Portable across every business. Owned by the masters.
  overlay    a business's delta. It may only POINT AT a node and add to it.
  candidate  what a business said that did not resolve. Kept verbatim, never
             bent into a term that nearly fits (مرام‌نامه، بند ۶).
"""
from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

# Equal search scores keep the published order: a family's buttons first, then its sequence.
SUGGEST_ORDER = 'featured desc, sequence, id'

class IkikuSpecNode(models.Model):
    _name = 'ikiku.spec.node'
    _inherit = ['search.suggest.mixin']
    _description = "گرهٔ استاندارد"
    _parent_store = True
    _order = 'complete_code'
    # What a person may type for a role or a skill, and how much each counts (search_suggest).
    _suggest_fields = {'plain_label': 1.0, 'name': 1.0, 'hint_terms': 0.9, 'name_en': 0.8,
                       'code': 0.6, 'description': 0.3}

    name = fields.Char("نام", required=True, translate=True)
    name_en = fields.Char("English name")
    plain_label = fields.Char(
        "نامِ ساده", help="همان کار به زبانِ روزمره، برای دکمه‌های ثبت‌نام. خالی یعنی همان نام.")
    featured = fields.Boolean(
        "دکمه‌ی اصلی", help="در ثبت‌نام و درخواستِ نیرو به‌صورتِ دکمه دیده می‌شود؛ بقیه‌ی نقش‌های "
                            "همان خانواده زیرِ «کارهای دیگه» می‌آیند.")
    country_rule_ids = fields.One2many('ikiku.spec.country.rule', 'node_id', string="عرضه در کشورها")
    sequence = fields.Integer(
        "ترتیبِ نمایش", default=100,
        help="ترتیبی که دکمه‌ها نشان داده می‌شوند؛ ثابت و منتشرشده، هرگز بر پایهٔ پرطرفداری.")
    code = fields.Char("کد", required=True, help="kebab-case، پایدار و بدون تغییر.")
    complete_code = fields.Char(compute='_compute_complete_code', store=True, recursive=True)
    kind = fields.Selection([
        ('family', "خانواده"),
        ('role', "نقش"),
        ('competency', "مهارت"),
        ('protocol', "دستورالعمل"),
        ('step', "گام"),
        ('attribute', "ویژگی"),
    ], string="نوع", required=True, default='competency')
    parent_id = fields.Many2one('ikiku.spec.node', string="والد", ondelete='restrict', index=True)
    parent_path = fields.Char(index=True, unaccent=False)
    child_ids = fields.One2many('ikiku.spec.node', 'parent_id', string="فرزندان")
    description = fields.Text("شرح")
    version = fields.Char("نسخه", default='1.0.0', required=True)
    hint_terms = fields.Text(
        "واژه‌های راهنما",
        help="واژه‌هایی که کاربر ممکن است به‌جای این گره بنویسد؛ یکی در هر خط. "
             "موتورِ راهنما با اینها متن آزاد را به گره استاندارد می‌رساند.")
    active = fields.Boolean(default=True)
    overlay_ids = fields.One2many('ikiku.spec.overlay', 'node_id', string="لایه‌های محلی")
    requirement_ids = fields.One2many('ikiku.spec.requirement', 'role_id', string="مهارت‌های لازم")
    used_by_ids = fields.One2many('ikiku.spec.requirement', 'skill_id', string="نقش‌هایی که لازمش دارند")
    knowledge_link_ids = fields.One2many('ikiku.knowledge.link', 'node_id', string="پیوند با دانش")
    promoted_from_id = fields.Many2one('ikiku.spec.candidate', string="ارتقا یافته از",
                                       readonly=True)

    _code_uniq = models.Constraint('UNIQUE(code)', "کد گره باید یکتا باشد.")

    @api.model
    def ikiku_country(self):
        """The country whose rules apply: the company's, or Iran where none is set."""
        return self.env.company.country_id or self.env.ref('base.ir')

    @api.model
    def ikiku_hidden_ids(self, country=None):
        """Ids of nodes not offered in `country`: every node under a rule with offered off,
        except the subtrees an offered rule lets back in."""
        country = country or self.ikiku_country()
        Rule = self.env['ikiku.spec.country.rule'].sudo()
        Node = self.sudo().with_context(active_test=False)
        blocked = Rule.search([('country_id', '=', country.id), ('offered', '=', False)]).node_id
        if not blocked:
            return []
        allowed = Rule.search([('country_id', '=', country.id), ('offered', '=', True)]).node_id
        hidden = set(Node.search([('id', 'child_of', blocked.ids)]).ids)
        if allowed:
            hidden -= set(Node.search([('id', 'child_of', allowed.ids)]).ids)
        return sorted(hidden)

    @api.model
    def ikiku_offered_domain(self, country=None):
        hidden = self.ikiku_hidden_ids(country)
        return [('id', 'not in', hidden)] if hidden else []

    @api.depends('code', 'parent_id.complete_code')
    def _compute_complete_code(self):
        for node in self:
            node.complete_code = (
                "%s/%s" % (node.parent_id.complete_code, node.code)
                if node.parent_id else node.code)

    @api.constrains('parent_id')
    def _check_acyclic(self):
        if self._has_cycle():
            raise ValidationError("درخت استاندارد نمی‌تواند حلقه داشته باشد.")

    @api.depends('name', 'complete_code')
    def _compute_display_name(self):
        for node in self:
            node.display_name = node.name or node.code

    @api.model
    def resolve_text(self, text, limit=5, kinds=('family', 'role', 'competency', 'attribute')):
        """Hint-and-steer: free text in, candidate standard nodes out, best first.

        search_suggest does the matching: folded Persian, typos, words written with or
        without ZWNJ, old words kept in hint_terms. It proposes; the person confirms, and
        every proposal can say which field and which kind of match found it.
        """
        domain = [('kind', 'in', list(kinds))] + self.ikiku_offered_domain()
        return self.browse([r['record'].id for r in self.suggest(text, domain=domain, limit=limit, order=SUGGEST_ORDER)])


class IkikuSpecOverlay(models.Model):
    _name = 'ikiku.spec.overlay'
    _description = "لایهٔ محلیِ کسب‌وکار"
    _order = 'business_id, sequence'

    name = fields.Char("عنوان", required=True)
    business_id = fields.Many2one('res.partner', string="کسب‌وکار", required=True,
                                  ondelete='cascade', index=True)
    node_id = fields.Many2one('ikiku.spec.node', string="گرهٔ استاندارد", required=True,
                              ondelete='restrict', index=True,
                              help="لایهٔ محلی فقط به یک گره اشاره می‌کند و به آن می‌افزاید؛ "
                                   "استاندارد را بازتعریف نمی‌کند.")
    sequence = fields.Integer(default=10)
    body = fields.Html("افزوده", sanitize=True, required=True)
    active = fields.Boolean(default=True)

    @api.constrains('body', 'node_id')
    def _check_is_addition(self):
        """An overlay that restates its node is a second copy that can disagree."""
        for rec in self:
            base = (rec.node_id.description or '').strip()
            if base and base in (rec.body or ''):
                raise ValidationError(
                    "لایهٔ محلی نباید متنِ گرهٔ استاندارد را تکرار کند. "
                    "فقط تفاوت را بنویسید؛ گره خودش خوانده می‌شود.")


class IkikuSpecCandidate(models.Model):
    _name = 'ikiku.spec.candidate'
    _description = "نامزدِ ورود به استاندارد"
    _order = 'occurrence desc, create_date desc'
    _inherit = ['mail.thread']

    name = fields.Char("متنِ خام", required=True, tracking=True,
                       help="عیناً همان چیزی که کاربر نوشت. هرگز اصلاح نمی‌شود.")
    business_id = fields.Many2one('res.partner', string="کسب‌وکار", index=True)
    proposed_by_id = fields.Many2one('res.partner', string="پیشنهاددهنده")
    source_model = fields.Char("مدل مبدأ")
    source_res_id = fields.Integer("شناسهٔ مبدأ")
    occurrence = fields.Integer("تکرار", default=1, tracking=True,
                                help="چند کسب‌وکار چیزی نزدیک به این گفته‌اند.")
    state = fields.Selection([
        ('new', "تازه"),
        ('queued', "در صفِ ارتقا"),
        ('promoted', "ارتقا یافته"),
        ('rejected', "ردشده"),
    ], default='new', required=True, tracking=True, string="وضعیت")
    promoted_node_id = fields.Many2one('ikiku.spec.node', string="گرهٔ حاصل", readonly=True)
    reject_reason = fields.Text("دلیلِ رد")

    PROMOTION_THRESHOLD = 3

    @api.model
    def record(self, text, business=None, partner=None, source=None, res_id=None):
        """Never drop the remainder. Cluster it if we have seen it before."""
        text = (text or '').strip()
        if not text:
            return self.browse()
        existing = self.search([('name', '=ilike', text), ('state', 'in', ('new', 'queued'))], limit=1)
        if existing:
            existing.occurrence += 1
            if existing.occurrence >= self.PROMOTION_THRESHOLD and existing.state == 'new':
                existing.state = 'queued'
                existing.message_post(
                    body="این نامزد در %d کسب‌وکار تکرار شده و به صفِ ارتقا رفت."
                         % existing.occurrence)
            return existing
        return self.create({
            'name': text,
            'business_id': business.id if business else False,
            'proposed_by_id': partner.id if partner else False,
            'source_model': source, 'source_res_id': res_id or 0,
        })

    def action_promote(self, parent=None, code=None, kind='competency'):
        """Promotion is a rule-change: a master does it, and it is logged."""
        self.ensure_one()
        if not self.env.user.has_group('ikiku_base.group_ikiku_master'):
            raise UserError("ارتقا به استاندارد فقط به دستِ مسئولِ فنیِ پلتفرم انجام می‌شود.")
        if self.state == 'promoted':
            raise UserError("این نامزد پیش‌تر ارتقا یافته است.")
        node = self.env['ikiku.spec.node'].create({
            'name': self.name,
            'code': code or ('cand-%d' % self.id),
            'kind': kind,
            'parent_id': parent.id if parent else False,
            'hint_terms': self.name,
            'promoted_from_id': self.id,
        })
        self.write({'state': 'promoted', 'promoted_node_id': node.id})
        self.message_post(body="ارتقا به استاندارد: %s" % node.complete_code)
        return node
