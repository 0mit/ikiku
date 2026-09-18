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
    # the operator's reports of 2026-09-18: on a form that asks for a city
    ("کاخ", None, "city"), ("فلسطین", None, "city"), ("کرشته", None, "city"), ("کیورثیه", None, "city"),
    ("فلسطین", None, "all"), ("بعثت", None, "all"), ("بعثت", None, "city"),
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
    position = {}
    for index, row in enumerate(rows):
        above = tree.chain(row['code'], parent_of)
        texts = tree.suggest_texts([row['name']], row['name_en'], row['code'], aliases.get(row['code'], []),
                                   [by_code[c]['name'] for c in above],
                                   [by_code[c]['name'] for c in neighbours.get(row['code'], [])])
        documents.append((row['code'], row['kind'], above, texts))
        position[row['code']] = index
    SEQ = 100   # a bundle carries no sequence: every place starts at 100
    out = []
    for query, within, kinds in CASES:
        started = time.time()
        allowed = set(tree.PICKER_KINDS[kinds]) if kinds else None
        # text.rank's own loop, kept unrounded: the best weight x value per place, the first
        # text in the place's list winning a tie -- then the climb, then the boost and rounding.
        best = {}
        for code, kind, above, texts in documents:
            top = None
            for field, weight, value in texts:
                match_kind, match_value = text.match(query, value)
                if match_kind and (top is None or weight * match_value > top[0]):
                    top = (weight * match_value, field, match_kind)
            if not top:
                continue
            step = tree.climb(kind, [(by_code[c]['kind'], True) for c in above], allowed)
            if step is None:
                continue
            target, via = (code, None) if step == 'self' else (above[step], code)
            have = best.get(target)
            if (have is None or top[0] > have[0]
                    or (top[0] == have[0] and have[3] is not None
                        and (via is None or position[via] < position[have[3]]))):
                best[target] = (top[0], top[1], top[2], via)
        results = []
        for code, (raw, field, match_kind, via) in best.items():
            inside = within and (code == within or within in tree.chain(code, parent_of))
            factor = 1.0 + tree.PARENT_WEIGHT if inside else 1.0
            above = [(by_code[c]['kind'], SEQ) for c in tree.chain(code, parent_of)]
            key = (SEQ, tree.city_sequence(by_code[code]['kind'], SEQ, above), position[code])
            results.append((-round(raw * factor, 4), key, {'code': code, 'score': round(raw * factor, 4),
                                                           'field': field, 'match': match_kind,
                                                           'via': via}))
        results.sort(key=lambda item: (item[0], item[1]))
        ranked = [item[2] for item in results[:LIMIT]]
        out.append({'q': query, 'within': within, 'kinds': kinds, 'results': ranked})
        print("%-16s %5.1fs  %s" % (query, time.time() - started, [r['code'] for r in ranked[:3]]))
    path = os.path.join(HERE, '..', 'testdata', 'rank_reference.json')
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(out, handle, ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
