# Part of search_suggest. Licensed under AGPL-3.0.
from odoo.tests import BaseCase, tagged

from odoo.addons.search_suggest.tools import text

DOCS = [
    ('dishes', [('name', 1.0, "شست‌وشوی ظرف"), ('hints', 0.9, "ظرفشور ظرف شور استیوارد")]),
    ('barista', [('name', 1.0, "باریستا"), ('name_en', 0.8, "Barista"), ('hints', 0.9, "قهوه‌ساز کافی من")]),
    ('cook', [('name', 1.0, "آشپز"), ('name_en', 0.8, "Cook")]),
    ('kebab', [('name', 1.0, "کباب‌پز"), ('name_en', 0.8, "Kebab cook")]),
    ('server', [('name', 1.0, "میزبان"), ('hints', 0.9, "گارسون پیشخدمت")]),
    ('club', [('name', 1.0, "باشگاه")]),
]


@tagged('post_install', '-at_install')
class TestText(BaseCase):

    def keys(self, query, limit=3):
        return [r['key'] for r in text.rank(query, DOCS, limit)]

    def test_folding(self):
        self.assertEqual(text.normalize("كافه يك"), "کافه یک")
        self.assertEqual(text.normalize("آشپزِ خطّ"), "اشپز خط")
        self.assertEqual(text.normalize("۱۲ و ٣٤"), "12 و 34")
        self.assertEqual(text.normalize("  Café,  CRÈME! "), "cafe creme")
        self.assertEqual(text.normalize("ظرف‌شستن"), "ظرف‌شستن")
        self.assertEqual(text.spaced("ظرف‌شستن"), "ظرف شستن")
        self.assertEqual(text.compact("ظرف شستن"), text.compact("ظرف‌شستن"))
        self.assertEqual(text.normalize("کبابــپز"), "کبابپز")

    def test_how_people_type_finds_the_right_thing(self):
        self.assertEqual(self.keys("ظرفشور")[0], 'dishes', "an old word kept as a hint")
        self.assertEqual(self.keys("گارسون")[0], 'server')
        self.assertEqual(self.keys("اشپز")[0], 'cook', "no madda")
        self.assertEqual(self.keys("كباب")[0], 'kebab', "Arabic kaf")
        self.assertEqual(self.keys("کبابپز")[0], 'kebab', "no ZWNJ")
        self.assertEqual(self.keys("باریسته")[0], 'barista', "a typo")
        self.assertEqual(self.keys("barista")[0], 'barista', "English")

    def test_short_queries_start_words_only(self):
        self.assertNotIn('club', self.keys("اش"))
        self.assertIn('club', self.keys("باش"))

    def test_results_say_why(self):
        exact = text.rank("آشپز", DOCS, 1)[0]
        self.assertEqual((exact['key'], exact['field'], exact['match'], exact['score']), ('cook', 'name', 'exact', 1.0))
        hint = text.rank("قهوه", DOCS, 1)[0]
        self.assertEqual((hint['field'], hint['match']), ('hints', 'phrase'))
        self.assertEqual(hint['score'], round(0.9 * text.MATCH_KINDS['phrase'], 4))

    def test_ties_keep_the_published_order(self):
        docs = [('b', [('name', 1.0, "کارِ ب")]), ('a', [('name', 1.0, "کارِ الف")])]
        self.assertEqual([r['key'] for r in text.rank("کار", docs)], ['b', 'a'])

    def test_nothing_for_nothing(self):
        self.assertEqual(text.rank("   ", DOCS), [])
        self.assertEqual(text.rank("zzzz", DOCS), [])
