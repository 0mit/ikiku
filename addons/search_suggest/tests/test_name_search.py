# Part of search_suggest. Licensed under AGPL-3.0.
"""The name-search opt-in's contract, on every model that opted in, whatever the project.

For `ilike` and a name with something in it, name_search answers what the model's suggest()
answers, in its order, with the names Odoo would show; anything else is Odoo's own name search,
unchanged. Each model's binding of name_search_cases proves the ranking itself."""
from odoo.models import BaseModel
from odoo.tests import TransactionCase, tagged

from odoo.addons.search_suggest.tools import text


@tagged('post_install', '-at_install')
class TestNameSearchContract(TransactionCase):

    def opted_in(self):
        return [name for name, model in self.env.registry.items()
                if not model._abstract and getattr(model, '_suggest_name_search', False)]

    def queries(self, Model):
        """Words the model's own rows begin with, as typed and as a keyboard with Arabic letters types them."""
        names = [record.display_name for record in Model.search([], limit=3)]
        words = [text.words(name)[0] for name in names if text.words(name)]
        return [word[:3] for word in words] + [word.replace('ی', 'ي').replace('ک', 'ك') for word in words]

    def test_off_unless_a_model_opts_in(self):
        self.assertFalse(self.env['search.suggest.mixin']._suggest_name_search)

    def test_it_answers_with_suggest_in_its_order(self):
        for name in self.opted_in():
            Model = self.env[name]
            for query in self.queries(Model):
                with self.subTest(model=name, query=query):
                    found = Model.name_search(query, [], 'ilike', 8)
                    ranked = Model._suggest_name_search_records(query, [], 8)
                    self.assertEqual([record_id for record_id, _name in found], ranked.ids)
                    self.assertEqual([shown for _id, shown in found], ranked.sudo().mapped('display_name'))

    def test_anything_else_is_odoos_own(self):
        for name in self.opted_in():
            Model = self.env[name]
            first = Model.search([], limit=1)
            for args in [(first.display_name, [], '=', 8), (first.display_name, [], '=ilike', 8),
                         (first.display_name, [], 'not ilike', 8), ('', [], 'ilike', 8),
                         ('   ', [], 'ilike', 8), (first.display_name, [], 'ilike', None)]:
                with self.subTest(model=name, args=args):
                    self.assertEqual(Model.name_search(*args), BaseModel.name_search(Model, *args))
