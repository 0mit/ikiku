# Part of search_suggest. Licensed under AGPL-3.0.
"""Text normalisation and ranking that know how people type, in Persian above all.

Nothing here touches the database, so it can be tested and reused on its own.

Normalisation folds what a keyboard, a phone or a habit changes but a reader does not:
  - Arabic letters Persian writing uses in their Persian form: ي ى ئ -> ی, ك -> ک, ة ۀ -> ه,
    أ إ ٱ آ -> ا, ؤ -> و (so «آشپز» matches «اشپز»);
  - diacritics and tatweel are dropped; Latin accents are dropped; case is folded;
  - Persian and Arabic-Indic digits become Latin digits;
  - ZWNJ is treated both as a space and as nothing, because «ظرف\u200cشستن», «ظرف شستن» and
    «ظرفشستن» are all written; every text is indexed in both forms;
  - punctuation becomes a space.

Ranking is readable: every score is the product of a field weight and a match kind from
MATCH_KINDS, and each result says which field and which kind produced it.
"""
import re
import unicodedata

ZWNJ = '\u200c'
FOLD = str.maketrans({
    'ي': 'ی', 'ى': 'ی', 'ئ': 'ی', 'ك': 'ک', 'ة': 'ه', 'ۀ': 'ه', 'ە': 'ه',
    'أ': 'ا', 'إ': 'ا', 'ٱ': 'ا', 'آ': 'ا', 'ؤ': 'و',
    '۰': '0', '۱': '1', '۲': '2', '۳': '3', '۴': '4', '۵': '5', '۶': '6', '۷': '7', '۸': '8', '۹': '9',
    '٠': '0', '١': '1', '٢': '2', '٣': '3', '٤': '4', '٥': '5', '٦': '6', '٧': '7', '٨': '8', '٩': '9',
    '\u0640': None, '\u200d': None, '\u200e': None, '\u200f': None,
})
MARKS = re.compile('[\u064b-\u065f\u0670\u06d6-\u06ed]')
NOT_WORD = re.compile(r'[^\w\u200c]+', re.UNICODE)
PLURAL_FA = ('های', 'ها')

# The published match kinds, strongest first. A result's score is weight x this value.
MATCH_KINDS = {
    'exact': 1.0,      # the whole text is the query
    'phrase': 0.85,    # the text contains the query as written, from the start of a word
    'words': 0.75,     # every word of the query starts a word of the text
    'compact': 0.6,    # matches once spaces and ZWNJ are ignored («ظرف\u200cشستن» ~ «ظرفشستن»)
    'partial': 0.45,   # some words of the query start words of the text
    'typo': 0.35,      # close in spelling (trigram similarity), for mistyped words
}
TYPO_THRESHOLD = 0.45


def normalize(text):
    """Lower-cased, folded text with single spaces; ZWNJ kept as a word joiner."""
    if not text:
        return ''
    text = unicodedata.normalize('NFKC', str(text)).translate(FOLD)
    text = MARKS.sub('', text)
    text = ''.join(c for c in unicodedata.normalize('NFKD', text) if unicodedata.category(c) != 'Mn'
                   or '\u0600' <= c <= '\u06ff')
    text = NOT_WORD.sub(' ', text.lower()).replace('_', ' ')
    return ' '.join(part.strip(ZWNJ) for part in text.split() if part.strip(ZWNJ))


def spaced(text):
    """ZWNJ read as a space."""
    return ' '.join(normalize(text).replace(ZWNJ, ' ').split())


def compact(text):
    """Spaces and ZWNJ removed: the form typed by someone who does not separate words."""
    return normalize(text).replace(ZWNJ, '').replace(' ', '')


def stem(word):
    """A light plural fold, Persian «ها/های» and English -s, for words long enough to keep meaning."""
    for suffix in PLURAL_FA:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[:-len(suffix)]
    if word.isascii() and word.endswith('s') and len(word) > 4:
        return word[:-1]
    return word


def words(text):
    return [stem(w) for w in spaced(text).split()]


def trigrams(word):
    padded = '  %s ' % word
    return {padded[i:i + 3] for i in range(len(padded) - 2)}


def similarity(a, b):
    """Trigram Jaccard similarity of two words, 0..1."""
    if not a or not b:
        return 0.0
    ta, tb = trigrams(a), trigrams(b)
    return len(ta & tb) / len(ta | tb)


def match(query, text):
    """(kind, value) of the best way `text` answers `query`, or (None, 0.0)."""
    q, t = spaced(query), spaced(text)
    if not q or not t:
        return None, 0.0
    if q == t:
        return 'exact', MATCH_KINDS['exact']
    if (' ' + t).find(' ' + q) >= 0:   # from the start of a word, not inside one
        return 'phrase', MATCH_KINDS['phrase']
    q_words, t_words = words(query), words(text)
    starts = [any(tw.startswith(qw) for tw in t_words) for qw in q_words]
    if starts and all(starts):
        return 'words', MATCH_KINDS['words']
    cq, ct = compact(query), compact(text)
    if len(cq) >= 3 and cq in ct:
        return 'compact', MATCH_KINDS['compact']
    if any(starts) and len(q_words) > 1:
        return 'partial', MATCH_KINDS['partial'] * sum(starts) / len(starts)
    best = max((similarity(qw, tw) for qw in q_words if len(qw) >= 3 for tw in t_words), default=0.0)
    best = max(best, similarity(cq, ct) if len(cq) >= 4 and len(ct) <= 2 * len(cq) else 0.0)
    if best >= TYPO_THRESHOLD:
        return 'typo', MATCH_KINDS['typo'] * best
    return None, 0.0


def rank(query, documents, limit=10):
    """Rank documents for a query.

    documents: iterable of (key, [(field, weight, text), ...]); a field may repeat, e.g. one
    text per language or per hint term. Returns [{'key', 'score', 'field', 'match'}] best first;
    ties keep the documents' own order, so a published order survives.
    """
    results = []
    for position, (key, fields) in enumerate(documents):
        best = None
        for field, weight, text in fields:
            kind, value = match(query, text)
            if kind and (best is None or weight * value > best[0]):
                best = (weight * value, field, kind)
        if best:
            results.append((-best[0], position, {'key': key, 'score': round(best[0], 4),
                                                 'field': best[1], 'match': best[2]}))
    results.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in results[:limit]]
