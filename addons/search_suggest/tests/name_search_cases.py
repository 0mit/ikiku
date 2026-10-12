# Part of search_suggest. Licensed under AGPL-3.0.
"""search_suggest's own cases (test_text.TestText), with each `rank` answered by Odoo's own name search.

A model that opts in (`_suggest_name_search = True`) proves it by binding these cases to itself,
beside its own tests -- search_suggest has no model of its own to bind them to:

    from odoo.addons.search_suggest.tests import test_text
    from odoo.addons.search_suggest.tests.name_search_cases import NameSearchCases

    @tagged('post_install', '-at_install')
    class TestRoleNameSearch(NameSearchCases, test_text.TestText, TransactionCase):
        _model = 'my.role'
        _fields = {'name': 'name', 'hints': 'synonyms', 'name_en': 'name_en'}   # the cases' field: the model's

        def _values(self, serial, position, key):        # what else a record needs
            return {'code': 'case-%d-%02d' % (serial, position)}

Each set of documents a case ranks becomes records, made in the documents' order (the binding
keeps the model's own order the same, which the ties case needs). `rank` asks name_search over
exactly those records and reads its answer back as keys, in name_search's order. The score,
field and match a case also checks are suggest()'s for the same records: name_search carries
the order, the reason is the ranking's own."""
from unittest.mock import patch

from odoo.addons.search_suggest.tools import text

from . import test_text


class _Text:
    """tools/text.py as test_text sees it, except `rank`."""

    def __init__(self, rank):
        self.rank = rank

    def __getattr__(self, name):
        return getattr(text, name)


class NameSearchCases:
    _model = None
    _fields = {}
    # Odoo 19 runs only the test methods a class defines itself unless told otherwise; the cases
    # are test_text's, inherited.
    allow_inherited_tests_method = True

    def _values(self, serial, position, key):
        return {}

    def setUp(self):
        super().setUp()
        patcher = patch.object(test_text, 'text', _Text(self._rank_by_name_search))
        patcher.start()
        self.addCleanup(patcher.stop)
        self._made = {}

    def _records_for(self, documents):
        """The records standing for `documents`, made once per set, and {id: the document's key}."""
        signature = repr(documents)
        if signature not in self._made:
            Model, serial = self.env[self._model], len(self._made)
            keys = {}
            for position, (key, fields) in enumerate(documents):
                values = self._values(serial, position, key)
                for field, _weight, value in fields:
                    name = self._fields[field]
                    values[name] = '%s\n%s' % (values[name], value) if values.get(name) else value
                keys[Model.create(values).id] = key
            self._made[signature] = (Model.browse(list(keys)), keys)
        return self._made[signature]

    def _rank_by_name_search(self, query, documents, limit=10, boost=None):
        records, key_of = self._records_for(list(documents))
        Model, domain = self.env[self._model], [('id', 'in', records.ids)]
        found = Model.name_search(query, domain, 'ilike', limit)
        why = {result['record'].id: result for result in Model.suggest(query, domain=domain, limit=limit)} \
            if text.spaced(query) else {}
        back = {name: field for field, name in self._fields.items()}
        return [{'key': key_of[record_id], 'score': why.get(record_id, {}).get('score'),
                 'field': back.get(why.get(record_id, {}).get('field')), 'match': why.get(record_id, {}).get('match')}
                for record_id, _name in found]
