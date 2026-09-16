# Part of iKiKu. Licensed under AGPL-3.0.
"""The business: the employer, and the owner of its own overlay.

A position is NOT a free-form job ad. It is an overlay: it must resolve to one
node of the standard tree, and whatever the owner said that did not resolve is
kept verbatim as a candidate. That is the whole generalisation engine, and it
runs on real hiring rather than on a taxonomy meeting.
"""
from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class IkikuBusiness(models.Model):
    _name = 'ikiku.business'
    _description = "کسب‌وکار"
    _inherit = ['mail.thread', 'ikiku.publishable']
    _order = 'name'

    partner_id = fields.Many2one('res.partner', string="دارنده", required=True,
                                 ondelete='restrict', index=True, tracking=True,
                                 help="کسی که حسابِ این کسب‌وکار را دارد. یک نفر می‌تواند چند کسب‌وکار داشته باشد.")
    # The business's own name, not the holder's: a portal signup gives the
    # business the person's partner, so a related name put the holder's personal
    # name on every position, demand and booking of the business.
    name = fields.Char("نام کسب‌وکار", required=True, tracking=True,
                       help="همان نامی که روی سردر است.")
    slug = fields.Char("نشانیِ عمومی", copy=False, index=True)
    # The café's own place. Until 2026-09-16 these were related to the holder's partner, so a
    # holder who also looks for work (operator, 2026-09-16) moved the café by saying where they
    # live, and a staff edit of the café moved the person. The columns and values are kept.
    province_id = fields.Many2one('ikiku.province', string="استان", tracking=True,
                                  help="جای کسب‌وکار، نه جای زندگیِ دارنده‌اش.")
    city = fields.Char("شهر", tracking=True)
    kind = fields.Selection([
        ('cafe', "کافه"), ('restaurant', "رستوران"),
        ('bakery', "نانوایی/قنادی"), ('other', "دیگر"),
    ], string="نوع", default='cafe', required=True)
    seats = fields.Integer("ظرفیت سالن")
    is_verified = fields.Boolean(related='partner_id.ikiku_is_verified', store=True,
                                 string="هویتِ دارنده تأییدشده",
                                 help="کدِ ملیِ دارنده بررسی شده؛ این بررسیِ خودِ کسب‌وکار نیست.")
    state = fields.Selection([
        ('draft', "پیش‌نویس"), ('active', "فعال"), ('suspended', "معلق"),
    ], default='draft', required=True, tracking=True, string="وضعیت")
    position_ids = fields.One2many('ikiku.position', 'business_id', string="جایگاه‌ها")
    overlay_ids = fields.One2many('ikiku.spec.overlay', 'business_id', string="لایه‌های محلی")

    # One person may hold several businesses (operator, 2026-09-16): no UNIQUE(partner_id).

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if not rec.slug:
                rec.slug = 'b-%d' % rec.id
        return records


class IkikuPosition(models.Model):
    _name = 'ikiku.position'
    _description = "جایگاه شغلی"
    _order = 'business_id, name'

    name = fields.Char("عنوانِ محلی", required=True,
                       help="هرچه خودتان می‌نامیدش. تغییرش نمی‌دهیم.")
    business_id = fields.Many2one('ikiku.business', required=True, ondelete='cascade',
                                  index=True, string="کسب‌وکار")
    spec_node_id = fields.Many2one(
        'ikiku.spec.node', string="گرهٔ استاندارد", required=True,
        domain="[('kind', 'in', ('competency', 'family'))]",
        help="این جایگاه به کدام مهارتِ استاندارد می‌رسد؟ بدون آن، نیرویی که "
             "جای دیگری آموزش دیده نمی‌فهمد این کار چیست.")
    raw_request = fields.Text("آنچه نوشتید",
                              help="متنِ آزادِ اولیه. نگه داشته می‌شود تا اگر استاندارد "
                                   "چیزی را از دست داده باشد، پیدا شود.")
    candidate_id = fields.Many2one('ikiku.spec.candidate', string="نامزدِ استاندارد",
                                   readonly=True)
    overlay_id = fields.Many2one('ikiku.spec.overlay', string="لایهٔ محلی")
    required_node_ids = fields.Many2many(
        'ikiku.spec.node', 'ikiku_position_required_rel', 'position_id', 'node_id',
        string="مهارت‌های الزامی")
    nice_node_ids = fields.Many2many(
        'ikiku.spec.node', 'ikiku_position_nice_rel', 'position_id', 'node_id',
        string="مهارت‌های مطلوب")
    active = fields.Boolean(default=True)

    @api.constrains('required_node_ids', 'nice_node_ids')
    def _check_no_double_listing(self):
        for rec in self:
            both = rec.required_node_ids & rec.nice_node_ids
            if both:
                raise ValidationError(
                    "یک مهارت نمی‌تواند هم الزامی باشد هم مطلوب: %s"
                    % ', '.join(both.mapped('name')))

    @api.model
    def steer(self, business, raw_text, chosen_node=None):
        """Hint and steer. Ask in their language, store in ours.

        The person types freely; we PROPOSE standard nodes; they confirm. What
        does not resolve is recorded as a candidate rather than discarded, so
        the standard can grow toward what businesses actually say.
        """
        Node = self.env['ikiku.spec.node']
        proposals = Node.resolve_text(raw_text)
        if chosen_node is None:
            return {'proposals': proposals, 'raw': raw_text}
        position = self.create({
            'name': raw_text[:64],
            'business_id': business.id,
            'spec_node_id': chosen_node.id,
            'raw_request': raw_text,
        })
        if chosen_node not in proposals:
            # The tree did not see this coming. Keep the words.
            position.candidate_id = self.env['ikiku.spec.candidate'].record(
                raw_text, business=business.partner_id,
                source='ikiku.position', res_id=position.id)
        return position
