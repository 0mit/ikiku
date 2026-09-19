# Part of iKiKu. Licensed under AGPL-3.0.
"""Roles, the skills they need, and the fields of knowledge those skills rest on.

Three relations, each many-to-many and each a row a person can read:

  requirement     a role needs a skill (core / common / specialist). One skill serves many
                  roles: milk texturing belongs to the barista and to the breakfast cook.
  knowledge link  a node (a role or a skill) sits in an international classification: a role
                  is classified as an ISCO-08 occupation; a skill draws on an ISCED-F 2013
                  field, and the link names the concept inside that field ("fluid pressure and
                  flow" in physics, for espresso). Overlaps between domains are the point.
  class           an entry of a published scheme, kept whole (every level), so later links and
                  a knowledge base never need a code that is not there.

  country rule    a node not offered in a country (operator, 2026-09-17: alcohol roles stay in
                  the tables but are not shown in Iran). A rule on a family covers its subtree;
                  an `offered` rule under it lets one node back in.

The portal shows roles, skills and the knowledge tree read-only (/roles, /skills, /knowledge).
The standard itself lives in ikiku_base/data/*.csv: edit the files, not the database, since an
update reloads them.
"""
from odoo import api, fields, models

KNOWLEDGE_RELATIONS = [
    ('classified_as', "ردهٔ رسمی"),
    ('draws_on', "بر پایهٔ این دانش"),
]
IMPORTANCE = [
    ('core', "اصلی"),
    ('common', "معمول"),
    ('specialist', "تخصصی"),
]


class IkikuKnowledgeScheme(models.Model):
    _name = 'ikiku.knowledge.scheme'
    _description = "طبقه‌بندیِ بین‌المللی"
    _order = 'code'

    code = fields.Char("کد", required=True, help="برای نمونه isced-f-2013 یا isco-08.")
    name = fields.Char("نام", required=True)
    name_en = fields.Char("English name")
    publisher = fields.Char("ناشر")
    url = fields.Char("نشانیِ منبع")
    notice = fields.Text("یادداشتِ منبع و ترجمه",
                         help="به فارسی، زیرِ هر صفحه‌ای که عنوان‌های این طبقه‌بندی را نشان می‌دهد.")
    notice_en = fields.Text("Source and translation notice",
                            help="The wording the publisher's licence or permission requires, verbatim.")
    kind = fields.Selection([('field', "رشته‌های دانش و آموزش"), ('occupation', "مشاغل")],
                            string="چه چیزی را رده‌بندی می‌کند", required=True)
    class_ids = fields.One2many('ikiku.knowledge.class', 'scheme_id', string="رده‌ها")

    _code_uniq = models.Constraint('UNIQUE(code)', "کدِ طبقه‌بندی باید یکتا باشد.")


class IkikuKnowledgeClass(models.Model):
    _name = 'ikiku.knowledge.class'
    _inherit = ['search.suggest.mixin']
    _description = "ردهٔ دانش یا شغل"
    _suggest_fields = {'name': 1.0, 'name_en': 0.9, 'code': 0.8}
    _parent_store = True
    _order = 'scheme_id, code'
    _rec_names_search = ['code', 'name', 'name_en']

    scheme_id = fields.Many2one('ikiku.knowledge.scheme', string="طبقه‌بندی", required=True,
                                ondelete='cascade', index=True)
    code = fields.Char("کد", required=True, index=True)
    name = fields.Char("نام", required=True)
    name_en = fields.Char("English name", required=True)
    level = fields.Char("سطح", help="همان نامِ سطح در منبع: broad، narrow، detailed، major، unit…")
    parent_id = fields.Many2one('ikiku.knowledge.class', string="والد", ondelete='restrict', index=True)
    parent_path = fields.Char(index=True)
    child_ids = fields.One2many('ikiku.knowledge.class', 'parent_id', string="زیررده‌ها")
    link_ids = fields.One2many('ikiku.knowledge.link', 'class_id', string="پیوندها")

    _scheme_code_uniq = models.Constraint('UNIQUE(scheme_id, code)', "کدِ رده در هر طبقه‌بندی یکتاست.")

    @api.depends('code', 'name', 'scheme_id.code')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = "%s %s — %s" % (rec.scheme_id.code or '', rec.code or '', rec.name or '')


class IkikuKnowledgeLink(models.Model):
    _name = 'ikiku.knowledge.link'
    _description = "پیوندِ کار یا مهارت با دانش"
    _order = 'node_id, relation, class_id'

    node_id = fields.Many2one('ikiku.spec.node', string="نقش یا مهارت", required=True,
                              ondelete='cascade', index=True)
    class_id = fields.Many2one('ikiku.knowledge.class', string="رده", required=True,
                               ondelete='restrict', index=True)
    scheme_id = fields.Many2one(related='class_id.scheme_id', store=True, string="طبقه‌بندی")
    relation = fields.Selection(KNOWLEDGE_RELATIONS, string="نسبت", required=True, default='draws_on')
    topic = fields.Char("موضوع", help="مفهومِ مشخص در آن رشته، برای نمونه «فشار و جریانِ سیال».")
    topic_en = fields.Char("Topic")
    note = fields.Text("توضیح")

    _link_uniq = models.Constraint('UNIQUE(node_id, class_id, relation, topic_en)',
                                   "این پیوند پیش‌تر ثبت شده است.")


class IkikuSpecRequirement(models.Model):
    _name = 'ikiku.spec.requirement'
    _description = "مهارتی که یک نقش لازم دارد"
    _order = 'role_id, importance, skill_id'

    role_id = fields.Many2one('ikiku.spec.node', string="نقش", required=True, ondelete='cascade',
                              index=True, domain="[('kind', '=', 'role')]")
    skill_id = fields.Many2one('ikiku.spec.node', string="مهارت", required=True, ondelete='cascade',
                               index=True, domain="[('kind', '=', 'competency')]")
    importance = fields.Selection(IMPORTANCE, string="اهمیت", required=True, default='core')
    note = fields.Char("توضیح")

    _role_skill_uniq = models.Constraint('UNIQUE(role_id, skill_id)', "این مهارت برای این نقش ثبت شده است.")


class IkikuSpecCountryRule(models.Model):
    _name = 'ikiku.spec.country.rule'
    _description = "عرضهٔ نقش یا مهارت در یک کشور"
    _order = 'country_id, node_id'

    node_id = fields.Many2one('ikiku.spec.node', string="نقش، مهارت یا خانواده", required=True,
                              ondelete='cascade', index=True)
    country_id = fields.Many2one('res.country', string="کشور", required=True, ondelete='cascade', index=True)
    offered = fields.Boolean("عرضه می‌شود", default=False,
                             help="خاموش: این گره و زیرشاخه‌هایش در این کشور نشان داده نمی‌شوند. "
                                  "روشن: گره‌ای را زیرِ شاخه‌ای که نشان داده نمی‌شود دوباره نشان می‌دهد.")
    reason = fields.Char("دلیل", required=True)

    _node_country_uniq = models.Constraint('UNIQUE(node_id, country_id)', "برای هر گره در هر کشور یک قاعده.")

