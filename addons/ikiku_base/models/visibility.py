# Part of iKiKu. Licensed under AGPL-3.0.
"""بند ۷ as data, not as per-field code.

Three classes, one interpreter. A field's class is a ROW, so changing what is
public is a data change a person can read and audit -- not a code change buried
in a serializer.

  public        anyone, no login. The professional record.
  counterparty  verified, logged-in businesses. Availability, relayed contact.
  restricted    platform staff with a logged reason. National ID, address,
                phone, and the venue and hours of any FUTURE shift.

Anything with no policy row is treated as `restricted`. Fail closed: a field
somebody forgot to classify must not become public by omission.
"""
from odoo import api, fields, models

CLASSES = [('public', "عمومی"), ('counterparty', "طرفِ تأییدشده"), ('restricted', "محدود")]


class IkikuVisibilityPolicy(models.Model):
    _name = 'ikiku.visibility.policy'
    _description = "سیاست نمایش میدان"
    _order = 'model_name, field_name'

    model_name = fields.Char("مدل", required=True, index=True)
    field_name = fields.Char("میدان", required=True)
    visibility = fields.Selection(CLASSES, string="ردهٔ نمایش", required=True, default='restricted')
    reason = fields.Char("چرا", required=True,
                         help="هر ردیف باید بگوید چرا در این رده است. بند ۳.")

    _field_uniq = models.Constraint('UNIQUE(model_name, field_name)',
                                    "برای هر میدان فقط یک ردیفِ سیاست.")


class IkikuPublishable(models.AbstractModel):
    """Mixin for anything with a public face."""
    _name = 'ikiku.publishable'
    _description = "قابلِ انتشار"

    @api.model
    def _visibility_map(self):
        policies = self.env['ikiku.visibility.policy'].sudo().search(
            [('model_name', '=', self._name)])
        return {p.field_name: p.visibility for p in policies}

    def ikiku_public_values(self, level='public'):
        """Return only the fields this level may see. Fails closed."""
        self.ensure_one()
        allowed = {'public'} if level == 'public' else {'public', 'counterparty'}
        if level == 'restricted':
            allowed |= {'restricted'}
        vmap = self._visibility_map()
        out = {}
        for fname, field in self._fields.items():
            klass = vmap.get(fname, 'restricted')
            if klass not in allowed:
                continue
            value = self[fname]
            if field.type in ('many2one',):
                value = value.display_name if value else False
            elif field.type in ('one2many', 'many2many'):
                value = value.mapped('display_name')
            out[fname] = value
        return out

    def ikiku_unclassified_fields(self):
        """Fields with no policy row. These are invisible to everyone until
        somebody classifies them -- this method is how you find them."""
        self.ensure_one()
        vmap = self._visibility_map()
        return sorted(f for f in self._fields if f not in vmap)
