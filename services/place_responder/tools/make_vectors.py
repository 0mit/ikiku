#!/usr/bin/env python3
# Part of place_responder. Licensed under AGPL-3.0.
"""Write the answers of search_suggest's text.py for the Go port to be checked against.

    python3 tools/make_vectors.py                 # testdata/text_vectors.json, a sample
    python3 tools/make_vectors.py --all OUT.json  # every name and alias in a bundle

The Python module is the published ranking; the Go one is a translation of it. These are
the translation's exam papers, set by the original. Regenerate after text.py changes.
"""
import argparse, csv, json, os, random, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'addons', 'search_suggest', 'tools'))
import text  # noqa: E402

BUNDLE = os.path.join(REPO, 'addons', 'place_ir', 'data')

# Hand-picked: every rule of normalize() and match() has a case here.
EDGE = [
    "ظرف‌شستن", "ظرف شستن", "ظرفشستن", "كاخ", "يزد", "آشپز", "اشپز", "مؤسسه", "ۀ", "خانهٔ",
    "۱۲۳ تهران", "٤٥ مشهد", "بَستنی", "قهوهــخانه", "Café Crème", "İstanbul", "STRASSE",
    "straße", "a_b-c.d", "  چند   فاصله  ", "‌نیم‌", "فروشگاه‌های", "ها", "کتابها", "coffees",
    "bus", "روستای فصلی تل کره", "منطقه ۶", "¹²³", "ﻻ", "ﷲ", "ﮐﺎﺥ",
]
QUERIES = ["ته", "تهر", "تهران", "کاخ", "فلسطین", "اندیشه شهریار", "علیشاه عوض", "شهریار", "منطقه ۶",
           "ظرفشستن", "ظرف شستن", "تهرن", "اصفهن", "مشهد مقدس", "ولیعصر", "انقلاب", "karaj", "tehran",
           "دانشگاه تهران", "ری", "قم", "باغ", "بازار", "خیابان", "کوچه", "فلسطين", "خيابان كاخ"]


def names(bundle):
    out = []
    for name in ('places.csv', 'aliases.csv'):
        path = os.path.join(bundle, name)
        if os.path.exists(path):
            with open(path, newline='', encoding='utf-8') as handle:
                out += [row['name'] for row in csv.DictReader(handle) if row.get('name')]
                if name == 'places.csv':
                    handle.seek(0)
                    out += [row['name_en'] for row in csv.DictReader(handle) if row.get('name_en')]
    return out


def vectors(strings, queries, texts):
    return {
        'text': [{'in': s, 'normalize': text.normalize(s), 'spaced': text.spaced(s),
                  'compact': text.compact(s), 'words': text.words(s)} for s in strings],
        'match': [{'q': q, 't': t, 'kind': k, 'value': v}
                  for q in queries for t in texts for k, v in [text.match(q, t)]],
        'round4': [{'in': x, 'out': round(x, 4)} for x in
                   [0.85 * 0.35, 0.75 * 1.35, 0.6 * 0.9 * 1.35, 0.35 * 0.47368421, 0.2975, 0.12345,
                    0.00005, 1.0 / 3.0, 0.45 * 2 / 3, 0.85 * 0.25 * 1.35]],
        'typo_threshold': text.TYPO_THRESHOLD,
        'match_kinds': text.MATCH_KINDS,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--all', metavar='OUT', help="every name in the bundle, to OUT")
    parser.add_argument('--bundle', default=BUNDLE)
    args = parser.parse_args()
    everything = names(args.bundle)
    if args.all:
        data = vectors(EDGE + everything, [], [])
        with open(args.all, 'w', encoding='utf-8') as handle:
            json.dump(data, handle, ensure_ascii=False)
        print("%d strings -> %s" % (len(data['text']), args.all))
        return
    rng = random.Random(20260918)
    sample = rng.sample(everything, min(2000, len(everything))) if everything else []
    texts = EDGE + rng.sample(everything, min(150, len(everything))) + [
        "تهران", "استان تهران", "خیابان فلسطین", "فلسطین", "کاخ", "اندیشه", "شهریار", "منطقه ۶",
        "دانشگاه تهران", "ته رود", "تهرانسر", "ظرف‌شستن", "Tehran", "Karaj", "ولی‌عصر", "ولیعصر"]
    data = vectors(EDGE + sample, QUERIES, texts)
    out = os.path.join(HERE, '..', 'testdata', 'text_vectors.json')
    with open(out, 'w', encoding='utf-8') as handle:
        json.dump(data, handle, ensure_ascii=False, indent=0)
    print("%d strings, %d match pairs -> %s" % (len(data['text']), len(data['match']), out))


if __name__ == '__main__':
    main()
