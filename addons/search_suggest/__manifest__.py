{
    'name': "Search and suggest",
    'summary': "Typo-tolerant, Persian-aware search with readable scores, and an accessible suggest box.",
    'description': """
Search and suggest
==================

A mixin a model inherits to be searched the way people type, and a small website widget
that suggests as they type.

* Text is folded before it is compared: Arabic letters into their Persian forms (ي→ی, ك→ک),
  diacritics and tatweel dropped, Persian and Arabic digits made Latin, ZWNJ read both as a
  space and as nothing, Latin accents and case folded.
* A result says why it was found: the field and one of six published match kinds (exact,
  phrase, words, compact, partial, typo), each with a fixed value multiplied by the field's
  weight. No learned ranking.
* A stored, normalised index narrows candidates in SQL; ranking runs in Python and falls back
  to a full scan of small sets so a typo in the first letters is still found.
* The widget is an ARIA combobox over a plain input. Without JavaScript the form still
  submits, so a page can offer the same results server-side.

Nothing here names a model of any project: declare `_suggest_fields` and call `suggest()`.
    """,
    'author': "شرکت تعاونی ایکیکو",
    'website': "https://ikiku.ir",
    'category': 'Hidden/Tools',
    'version': '19.0.1.0.0',
    'license': 'AGPL-3',
    'depends': ['web'],
    'assets': {
        'web.assets_frontend': [
            'search_suggest/static/src/scss/search_suggest.scss',
            'search_suggest/static/src/js/search_suggest.js',
        ],
    },
    'installable': True,
}
