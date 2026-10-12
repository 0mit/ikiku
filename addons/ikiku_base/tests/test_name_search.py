# Part of iKiKu. Licensed under AGPL-3.0.
"""The back office finds a role, a skill or a class of knowledge the way people type them.

The roles and skills of the standard and the classes of ISCO and ISCED-F opt in to
search_suggest's name search, so a many2one's box ranks them as the site does: «اشپز» without
its madda, «كباب» with an Arabic kaf, «ظرفشور» kept as a hint, «باریسته» mistyped. Before, Odoo's
own `ilike` on the name found none of these."""
from odoo.tests import TransactionCase, tagged

from odoo.addons.search_suggest.tests import test_text
from odoo.addons.search_suggest.tests.name_search_cases import NameSearchCases


@tagged('post_install', '-at_install')
class TestSpecNodeNameSearch(NameSearchCases, test_text.TestText, TransactionCase):
    """search_suggest's own six cases, each answered by the spec tree's name_search."""
    _model = 'ikiku.spec.node'
    _fields = {'name': 'name', 'hints': 'hint_terms', 'name_en': 'name_en'}

    def _values(self, serial, position, key):
        # The tree's order is its codes', so the cases' documents keep their own order.
        return {'code': 'name-search-case-%d-%02d' % (serial, position), 'kind': 'role'}


@tagged('post_install', '-at_install')
class TestKnowledgeClassNameSearch(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        scheme = cls.env['ikiku.knowledge.scheme'].create({'name': "آزمون", 'code': 'NS-TEST', 'kind': 'occupation'})
        Class = cls.env['ikiku.knowledge.class']
        cls.cooks = Class.create({'scheme_id': scheme.id, 'code': '5120', 'name': "آشپزها", 'name_en': "Cooks"})
        cls.chefs = Class.create({'scheme_id': scheme.id, 'code': '3434', 'name': "سرآشپزها", 'name_en': "Chefs"})
        cls.waiters = Class.create({'scheme_id': scheme.id, 'code': '5131', 'name': "گارسون‌ها", 'name_en': "Waiters"})
        cls.domain = [('scheme_id', '=', scheme.id)]

    def found(self, query):
        return [record_id for record_id, _name in self.env['ikiku.knowledge.class'].name_search(query, self.domain)]

    def test_typed_as_people_type(self):
        self.assertEqual(self.found("اشپزها")[0], self.cooks.id, "no madda")
        self.assertEqual(self.found("گارسونها")[0], self.waiters.id, "no ZWNJ")
        self.assertEqual(self.found("٥١٢٠")[0], self.cooks.id, "a code in Arabic-Indic digits")
        self.assertEqual(self.found("chef")[0], self.chefs.id, "the English name")

    def test_a_name_called_this_comes_before_one_containing_it(self):
        self.assertEqual(self.found("آشپزها"), [self.cooks.id, self.chefs.id])
