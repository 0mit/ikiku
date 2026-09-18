#!/usr/bin/env python3
# Part of place_responder. Licensed under AGPL-3.0.
"""The ranking's answer key: search_suggest's rank() over EVERY place of a bundle.

    python3 tools/make_rank_reference.py      # testdata/rank_reference.json

No shortlist, no cap: each place's texts (place_graph's tree.suggest_texts) are ranked with
text.rank(), in bundle order, which is also the tie order. The responder must give the same
places, scores, fields and match kinds. Slow on purpose -- it is the definition, not the
implementation.
"""
import csv, json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'addons', 'place_graph', 'tools'))
import bundle, tree  # noqa: E402
text = tree.text

BUNDLE = os.path.join(REPO, 'addons', 'place_ir', 'data')
# (query, within code or None, picker kinds or None)
CASES = [
    ("ته", None, "all"), ("تهران", None, "all"), ("کاخ", "ir-tehran", "all"), ("فلسطین", None, "all"),
    ("اندیشه شهریار", None, "all"), ("علیشاه عوض", None, "all"), ("منطقه ۶", None, "all"),
    ("تهرن", None, "all"), ("اصفهن", None, "city"), ("karaj", None, "all"), ("ولیعصر", None, "all"),
    ("دانشگاه تهران", None, "all"), ("ری", None, "city"), ("قم", None, "all"), ("خيابان كاخ", None, "all"),
    ("شهرک غرب", None, "area"), ("باغ", None, "all"),
]
LIMIT = 10


def main():
    data = bundle.read(BUNDLE)
    rows = data['places']
    by_code = {row['code']: row for row in rows}
    parent_of = {row['code']: row['parent'] for row in rows if row['parent']}
    aliases, neighbours = {}, {}
    for a in sorted(data['aliases'], key=lambda r: (r['kind'], r['name'])):
        aliases.setdefault(a['place'], []).append((a['name'], a['kind']))
    for link in data['links']:
        neighbours.setdefault(link['place'], []).append(link['other'])
        neighbours.setdefault(link['other'], []).append(link['place'])
    documents = []
    for row in rows:
        above = tree.chain(row['code'], parent_of)
        texts = tree.suggest_texts([row['name']], row['name_en'], row['code'], aliases.get(row['code'], []),
                                   [by_code[c]['name'] for c in above],
                                   [by_code[c]['name'] for c in neighbours.get(row['code'], [])])
        documents.append((row['code'], row['kind'], set(above) | {row['code']}, texts))
    out = []
    for query, within, kinds in CASES:
        started = time.time()
        allowed = set(tree.PICKER_KINDS[kinds]) if kinds else None
        docs = [(code, texts) for code, kind, _up, texts in documents if not allowed or kind in allowed]
        inside = {code for code, _kind, up, _texts in documents if within and within in up}
        boost = (lambda key: 1.0 + tree.PARENT_WEIGHT if key in inside else 1.0) if within else None
        ranked = text.rank(query, docs, LIMIT, boost=boost)
        out.append({'q': query, 'within': within, 'kinds': kinds,
                    'results': [{'code': r['key'], 'score': r['score'], 'field': r['field'],
                                 'match': r['match']} for r in ranked]})
        print("%-16s %5.1fs  %s" % (query, time.time() - started, [r['key'] for r in ranked[:3]]))
    path = os.path.join(HERE, '..', 'testdata', 'rank_reference.json')
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(out, handle, ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
