# Part of search_suggest. Licensed under AGPL-3.0.
"""The mixin: declare what is searched and how much each field counts, then call suggest().

    class Role(models.Model):
        _inherit = ['my.role', 'search.suggest.mixin']
        _suggest_fields = {'name': 1.0, 'synonyms': 0.9, 'description': 0.3}

    Role.suggest("باریسته", domain=[('active', '=', True)], limit=8)
    -> [{'record': my.role(12,), 'score': 0.21, 'field': 'name', 'match': 'typo'}, ...]

Translated fields are read in every installed language, so a Persian page finds an English
name and the other way round. `suggest_index` is the folded text of all of it, stored so SQL
can narrow the candidates before the readable ranking in tools/text.py decides the order.
"""
from odoo import api, fields, models

from odoo.addons.search_suggest.tools import text as suggest_text

SCAN_LIMIT = 5000   # below this many records in the domain, a miss in SQL is re-checked in full


class SearchSuggestMixin(models.AbstractModel):
    _name = 'search.suggest.mixin'
    _description = "Search and suggest"

    # field name -> weight (0..1). Override in the inheriting model.
    _suggest_fields = {}

    suggest_index = fields.Text(
        "Search index", compute='_compute_suggest_index', store=True, readonly=True, copy=False,
        help="The searched fields, folded for comparison. Rebuilt when they change.")

    @api.depends(lambda self: tuple(self._suggest_fields))
    def _compute_suggest_index(self):
        for record in self:
            texts = []
            for _field, _weight, value in record._suggest_texts():
                texts.append(suggest_text.spaced(value))
                texts.append(suggest_text.compact(value))
            record.suggest_index = ' '.join(t for t in texts if t)

    def _suggest_texts(self):
        """(field, weight, text) for this record, every translated field in every installed language."""
        self.ensure_one()
        languages = [code for code, _name in self.env['res.lang'].get_installed()] or [None]
        out = []
        for name, weight in self._suggest_fields.items():
            field = self._fields.get(name)
            if not field:
                continue
            seen = set()
            for lang in (languages if field.translate else [None]):
                record = self.with_context(lang=lang) if lang else self
                value = record[name]
                if field.type == 'many2one':
                    value = value.display_name
                if value and value not in seen:
                    seen.add(value)
                    out.append((name, weight, str(value)))
        return out

    @api.model
    def suggest(self, query, domain=None, limit=10, order=None):
        """Records for `query`, best first, each with its score and the reason it was found.
        Equal scores keep `order` (default: the model's own), so a published order breaks ties."""
        query = (query or '').strip()
        if not suggest_text.spaced(query):
            return []
        domain = list(domain or [])
        words = [w for w in suggest_text.words(query) if w]
        narrowing = []
        for word in words + [suggest_text.compact(query)]:
            piece = word[:3] if len(word) >= 3 else word
            if piece:
                narrowing.append(('suggest_index', 'ilike', piece))
        candidates = self.search(domain + (['|'] * (len(narrowing) - 1)) + narrowing, order=order) \
            if narrowing else self.browse()
        results = self._suggest_rank(query, candidates, limit)
        if len(results) < limit and self.search_count(domain, limit=SCAN_LIMIT + 1) <= SCAN_LIMIT:
            # A typo in the first letters escapes the SQL narrowing; small sets are checked in full.
            everything = self.search(domain, order=order)
            if len(everything) > len(candidates):
                results = self._suggest_rank(query, everything, limit)
        return results

    @api.model
    def _suggest_rank(self, query, records, limit):
        by_id = {record.id: record for record in records}
        ranked = suggest_text.rank(query, ((record.id, record._suggest_texts()) for record in records), limit)
        return [dict(result, record=by_id[result.pop('key')]) for result in ranked]
