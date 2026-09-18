# place_responder

A place search that answers while a person is still typing. It holds a country's places in
memory and ranks them **exactly** as [search_suggest](../../addons/search_suggest) publishes:
the same folding of Persian text, the same six match kinds, the same weights. It ranks every
place, with no shortlist. It only reads. What a person picks goes back to the application
that owns the data, as an `id` or a `code`, and that application checks it.

It is written to be reusable, and it is **not** offered as a public service. It has no
accounts, no per-caller quotas and no promise of being up. Run your own copy next to your
own application.

## Where the places come from

| source | how | kept current by |
|---|---|---|
| an Odoo database with `place_graph` | `-dsn` or `-dsn-file`, as a read-only role | `NOTIFY place_graph_changed` from place_graph's triggers (sent at COMMIT), plus a statistics poll as a safety net |
| a place bundle on disk | `-bundle DIR`, repeatable: later directories overlay earlier ones by `code` | the manifest's checksums, polled |

A bundle is plain CSV files plus a manifest with their checksums, sources and licences. It
is made outside any application by `addons/place_graph/tools/bundle.py`, and for Iran it
comes from `osm_import.py`. With a bundle you need no Odoo at all:

    place_responder -bundle addons/place_ir/data -listen 127.0.0.1:8070
    curl '127.0.0.1:8070/places/suggest?q=کاخ&within=ir-tehran'

## Asking

    GET /places/suggest?q=&kinds=&within=&limit=&lang=        (also /suggest)

    {"results": [{"id": 97413, "code": "ir-palestine-street-3", "label": "فلسطین",
                  "detail": "فلسطین · فلسطین - انقلاب · تهران", "kind": "street",
                  "score": 1.215, "field": "alias", "match": "exact", "boost": 1.35,
                  "point": [35.6976, 51.402253]}],
     "generation": 3}

- `kinds` is a named set from the spec (`city`, `area`, `all`) or a comma-separated list of kinds.
- `within` is a place id or code. Places inside it are lifted by the spec's `within_boost`.
- `limit` defaults to 8 and is capped at 25.
- A query that is a post code (five or more digits) is cut to its first five and answered
  from the prefix table. The rest of the code is never read, kept or logged.
- `score`, `field` and `match` say why each place was found. The ranking is published, and a
  caller is entitled to check it.

The admin listener (loopback by default, never proxied) serves `GET /healthz` (what is
loaded, from where, how old, how long it took) and `POST /reload`. `SIGHUP` also reloads.

## How it stays exact

- `text.go` is a line-for-line translation of `search_suggest/tools/text.py`.
  `tools/make_vectors.py` writes the Python module's own answers to
  `testdata/text_vectors.json`, and `go test` fails on the first disagreement. With
  `--all`, the check covers every name in a bundle (152,517 for Iran; all agree).
- `tools/make_rank_reference.py` ranks every place of the bundle with Python's `rank()`,
  which takes 7 to 33 seconds a query. `TestRankingMatchesPython` requires the same places,
  order, scores, fields and match kinds from the responder, which takes 0.2 to 9 ms a query.
- The weights are not the responder's own. Odoo publishes `place_graph`'s `tree.spec()` into
  the view `place_responder_spec`, and a bundle carries the same spec in its manifest. The
  built-in defaults are used only when a source publishes nothing, and `/healthz` says so.

## What it costs

On the Iran bundle (103,415 places): about 110 MiB of live heap, a 2–6 s build that happens
beside the index in use (so nobody waits), and 5 ms a search on one core across a deliberately
heavy query mix. Answers are cached per data generation. Run it with `GOMAXPROCS=1` and
`GOMEMLIMIT=300MiB`; `deploy/compose.places.yml` also caps the container at 400 MB and half a
core.

## Building and deploying

    cd deploy
    make test            # vet + tests, including parity with the Python ranking
    make save            # static binary -> FROM scratch image -> place-responder-<version>.tar.gz

`deploy/` has the image, the compose service, the nginx location with its rate limit, and the
read-only role (`places_ro.sql`). That role can read the four place tables, the languages and
the spec view. It cannot read the rest of `ir_config_parameter`, which holds secrets. The
page asks the responder at the path set in the system parameter `place_graph.responder_url`.
When the responder doesn't answer, the page falls back to Odoo's own `/places/suggest`.
That fallback has the same ranking and is only slower.

## Licence

AGPL-3.0, like the rest of this repository. The Iran data it is usually run with is © OpenStreetMap
contributors under the ODbL 1.0: a page that shows these places has to say so.
