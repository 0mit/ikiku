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
import logging

from odoo import api, fields, models

from odoo.addons.search_suggest.tools import text as suggest_text

_logger = logging.getLogger(__name__)

SCAN_LIMIT = 5000   # below this many records in the domain, a miss in SQL is re-checked in full
PREFIX = 3          # letters of a word kept when looking for a word that was mistyped
CANDIDATE_LIMIT = 400    # most rows ever read for one query, whatever the query matches
WHOLE_WORD_MIN = 3  # shorter than this, «called exactly this» is not what anybody means yet
SHORTLIST = 60      # rows ranked in full when there are more candidates than that


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

    def init(self):
        """A trigram index on the stored index, so narrowing stays a lookup as the table grows.

        `ilike '%piece%'` cannot use an ordinary index: on a few hundred rows that is a scan
        nobody feels, on tens of thousands of places it is the whole query. pg_trgm makes it
        an index lookup. It is optional on purpose -- a database that will not create the
        extension keeps working, more slowly, and says so once."""
        super().init()
        if self._abstract or not self._auto or not self._fields.get('suggest_index'):
            return
        with self.env.cr.savepoint(flush=False):
            try:
                self.env.cr.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
                self.env.cr.execute(
                    'CREATE INDEX IF NOT EXISTS "%s_suggest_index_trgm" ON "%s" '
                    'USING gin (suggest_index gin_trgm_ops)' % (self._table, self._table))
            except Exception as error:
                _logger.info("search_suggest: no trigram index on %s (%s); search still works.",
                             self._table, error)

    def _suggest_texts(self):
        """(field, weight, text) for this record, every translated field in every installed language."""
        self.ensure_one()
        languages = [code for code, _name in self.env['res.lang'].get_installed()] or [None]
        if len(languages) == 1:
            languages = [None]      # the record as it is: no second reading to fetch
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
    def suggest(self, query, domain=None, limit=10, order=None, boost=None, widen=True):
        """Records for `query`, best first, each with its score and the reason it was found.
        Equal scores keep `order` (default: the model's own), so a published order breaks ties.

        boost: [(domain, factor), ...] for context the asker is already in -- the city they
        picked, the family they are browsing. A record the domain matches has its score
        multiplied. It lifts what already matched and never adds a record, so a boosted
        result is still found for the reason it says.

        widen=False answers from the first, tightest search only -- what a page shows while
        the rest is still coming, so something true is on the screen in a few milliseconds
        instead of nothing for a quarter of a second. The scores are the same either way; the
        wide answer only adds records the tight one could not see."""
        query = (query or '').strip()
        if not suggest_text.spaced(query):
            return []
        domain = list(domain or [])
        words = [word for word in suggest_text.words(query) if word]
        compact = suggest_text.compact(query)
        prefixes = [word[:PREFIX] for word in words if len(word) > PREFIX]

        # The tightest search that answers is the one that answers. Each attempt below is
        # wider than the last, and the ranking is the same in all of them; a wider attempt
        # only runs when the tighter one came back with less than the asker wanted. This is
        # what keeps a common word cheap: «تهران» is in tens of thousands of rows, and
        # nothing ranks all of them for a query that also said «دانشگاه».
        # The quick answer is the FIRST of the attempts below and nothing else: what is
        # called this, ranked the same way. It can miss what a wider attempt would find -- a
        # mistyped word, letters inside a longer word -- which is why it is what a page shows
        # while the full answer is still coming, and never what it settles on.
        if not widen:
            quick = words + ([compact] if compact not in words else [])
            attempts = [self._suggest_any_of(quick, how='whole' if len(compact) >= WHOLE_WORD_MIN
                                            else 'start')]
        else:
            # From what is called this, out to what merely contains these letters. Each is
            # wider and dearer than the last, and a wider one is only asked when the tighter
            # came back with less than the asker wanted.
            attempts = []
            everything = words + ([compact] if compact not in words else [])
            # A word of one or two letters is somebody mid-way through typing, not somebody
            # naming a place: «ته» is the start of «تهران» far more often than it is the whole
            # name of «ته رود», so for a query that short the first attempt is skipped.
            if len(compact) >= WHOLE_WORD_MIN:
                if len(words) > 1:
                    attempts.append(self._suggest_all_of(words, how='whole'))
                attempts.append(self._suggest_any_of(everything, how='whole'))
            if len(words) > 1:
                attempts.append(self._suggest_all_of(words, how='start'))
            attempts.append(self._suggest_any_of(everything, how='start'))
            if prefixes:
                attempts.append(self._suggest_any_of(prefixes, how='start'))   # for typos
            # Last: the letters anywhere, even inside a word. The only attempt that can find a
            # `compact` match inside a longer word, and the only one whose cost does not fall
            # with how much of the query was typed -- so it is asked last.
            attempts.append(self._suggest_any_of(everything, how='anywhere'))
        candidates, results = self.browse(), []
        for attempt in attempts:
            # A wider attempt ADDS to what the tighter ones found, never replaces it: its own
            # 400 rows are the first 400 in the published order, and a tight match that sorts
            # late -- a street called «کاخ», behind every village and neighbourhood that merely
            # begins with it -- must not be pushed out by rows that match worse.
            found = candidates | self.search(domain + attempt, order=order, limit=CANDIDATE_LIMIT)
            if len(found) <= len(candidates):
                continue
            candidates = found
            results = self._suggest_rank(query, candidates, limit, boost)
            if len(results) >= limit:
                return results
        if widen and len(results) < limit \
                and self.search_count(domain, limit=SCAN_LIMIT + 1) <= SCAN_LIMIT:
            # A typo in the first letters escapes every search above; small sets are read whole.
            everything = self.search(domain, order=order)
            if len(everything) > len(candidates):
                results = self._suggest_rank(query, everything, limit, boost)
        return results

    @api.model
    def _suggest_whole_word(self, piece):
        """A piece as a COMPLETE word of the index: «کاخ», not «کاخک».

        This is the first thing worth asking, and it is the cheapest: it separates the rows
        that are called this from the many more that merely begin this way, so what comes
        back is small enough to rank in full and already the best of what there is."""
        return ['|', '|', '|',
                ('suggest_index', '=ilike', piece),
                ('suggest_index', '=ilike', '%s %%' % piece),
                ('suggest_index', '=ilike', '%% %s' % piece),
                ('suggest_index', '=ilike', '%% %s %%' % piece)]

    @api.model
    def _suggest_word_start(self, piece):
        """A piece at the START of a word of the index -- the only place it can earn a score.

        Every match kind above `typo` requires the query to begin a word (see tools/text.py),
        so a row that merely contains the letters inside a longer word was read, ranked and
        thrown away. On a small table nobody notices; on a hundred thousand places, «ته»
        matched tens of thousands of rows and took seconds to answer. The index stores each
        text spaced and compact, and both forms start a word, so nothing findable is lost."""
        return ['|', ('suggest_index', '=ilike', '%s%%' % piece),
                     ('suggest_index', '=ilike', '%% %s%%' % piece)]

    @api.model
    def _suggest_terms(self, piece, how):
        if how == 'whole':
            return self._suggest_whole_word(piece)
        if how == 'start':
            return self._suggest_word_start(piece)
        return [('suggest_index', 'ilike', piece)]      # anywhere, even inside a word

    @api.model
    def _suggest_all_of(self, pieces, how='start'):
        domain = []
        for piece in [piece for piece in pieces if piece]:
            domain += self._suggest_terms(piece, how)
        return domain

    @api.model
    def _suggest_any_of(self, pieces, how='start'):
        pieces = [piece for piece in pieces if piece]
        if not pieces:
            return []
        parts = [self._suggest_terms(piece, how) for piece in pieces]
        return (['|'] * (len(parts) - 1)) + [term for part in parts for term in part]

    @api.model
    def _suggest_rank(self, query, records, limit, boost=None):
        # The boost is worked out BEFORE the shortlist and used by it: the whole point of
        # «the city you are already in» is that it decides between rows of the same name, and
        # a shortlist that could not see it would throw the right one away first.
        factors = self._suggest_boost_factors(records, boost)
        records = self._suggest_shortlist(query, records, limit, factors)
        by_id = {record.id: record for record in records}
        ranked = suggest_text.rank(query, ((record.id, record._suggest_texts()) for record in records),
                                   limit, boost=factors.get if factors else None)
        return [dict(result, record=by_id[result.pop('key')]) for result in ranked]

    @api.model
    def _suggest_shortlist(self, query, records, limit, factors=None):
        """The records worth ranking properly, when there are too many to rank properly.

        The full ranking reads every text about a record -- its names, its aliases, the names
        above it. The stored index already holds all of that as one string, so a first pass
        over the index alone puts the plausible rows in front for the price of one query. It
        decides nothing: the scores that are returned all come from the full pass.
        """
        if len(records) <= max(SHORTLIST, limit):
            return records
        records.fetch(['suggest_index'])
        keep = max(SHORTLIST, limit)
        scored = []
        for position, record in enumerate(records):
            score = suggest_text.quick_score(query, record.suggest_index or '')
            if score:
                scored.append((-score * (factors.get(record.id, 1.0) if factors else 1.0),
                               position, record.id))
        scored.sort()
        return records.browse([record_id for _score, _position, record_id in scored[:keep]])

    @api.model
    def _suggest_boost_factors(self, records, boost):
        """id -> factor for the records a boost domain matches. The domains are read in
        memory against the candidates already found, so a boost costs no second query."""
        factors = {}
        for domain, factor in (boost or ()):
            for record in records.filtered_domain(domain):
                factors[record.id] = factors.get(record.id, 1.0) * factor
        return factors
