# Where Iran's places could come from: a reckoning (2026-09-18)

What is openly available beyond the OpenStreetMap extract `place_ir` is built from, what each
source would add, and what its licence would oblige a repository to do. The repository is
AGPL-3.0 and it publishes the derived names in `data/`.

Measured means counted from the source on the date above. Stated means taken from the
source's own terms.

| source | what it has for Iran | licence (stated) | what it obliges | worth it? |
|---|---|---|---|---|
| **OpenStreetMap** (Geofabrik extract), in use | 103,415 places as a tree, 11,477 aliases, 16,152 neighbour pairs (measured) | ODbL 1.0 | attribution; derived databases stay ODbL | the base; already here |
| **Wikidata** | 135,907 Iranian items with coordinates; 8,621 of them carry Persian aliases, 15,073 aliases in all (measured). Former and colloquial names are there: Q2663243 (شهریار) carries «علیشاه عوض» | CC0 | nothing | **yes: the cheapest win for old names** |
| **GeoNames** (`IR.zip` + `alternatenames/IR.zip`) | 254,642 features, 81,839 populated places; 322,475 Persian name strings. 56,782 Persian names on 47,022 populated or admin features are not in our tree (measured). Almost no historic or colloquial flags (67 and 9) | CC BY 4.0 | attribution to GeoNames, in the manifest and on the page that credits OSM | **yes, for village coverage**, through the suggestion queue |
| **Statistical Centre of Iran** census village lists (via github.com/ahmadazizi/iran-cities) | province, county, bakhsh, dehestan, city and ~98,100 villages with official codes, as of 1399 (2020). No coordinates: the Centre has not released them | the repo is MIT. The Centre's own data carries no open licence we could find | the names are facts. The official codes and the list itself are the Centre's, and their terms are unknown | as a **check** of names and hierarchy, not as a shipped source |
| **OCHA COD-AB** (HDX) | admin levels 0–2 (country, province, bakhsh), reviewed Oct 2024 | CC BY 3.0 IGO | attribution | little: OSM already has these, with boundaries |
| **geoBoundaries** | ADM0–ADM2 boundaries | CC BY 4.0 (per boundary, from its source) | attribution | a fallback for provinces cut by the extract (Bushehr) |
| **GADM** | admin boundaries | academic and non-commercial only; "redistribution or commercial use is not allowed without prior permission" | **not usable** | no |
| **Neshan, Map.ir** (Iranian map APIs) | geocoding and search, including post codes | proprietary; storing results is not granted | a contract | no, as a source. Possibly a paid lookup later, never cached into `data/` |
| **Nominatim / Overpass** (one-time fetch) | the same OSM data, served live | ODbL; Nominatim forbids bulk use | as OSM | no: the extract is the same data without the load on a volunteer service |

## Post codes: is there a source that settles it once and for all?

No. We looked and found none that is open and complete:

- **Iran Post** publishes no open table from prefix to area. Its official lookup (GNAF) is a
  contracted service. That would be a contract, not a download, and its terms would decide
  whether anything learned from it may be stored.
- **GeoNames** has no Iranian postal file (`export/zip/IR.zip` returns 404) and one Iranian
  code in its alternate names.
- **Wikidata** has 58 postal codes on 56 Iranian items.
- **OpenStreetMap** tags 4,478 objects in Iran with a valid ten-digit `addr:postcode`,
  covering 2,149 distinct five-digit prefixes, 487 of them seen three or more times (measured
  in the same extract). It is real, ODbL, and patchy: good in the parts of Tehran that
  mappers walk, thin elsewhere.

So the plan the operator chose on 2026-09-18 ("seed a prefix table, then learn") has one
honest seed: OSM's `addr:postcode`. Each tagged object is placed with the same
point-in-boundary step `osm_import.py` already uses, and the five-digit prefix and the place
are written into the bundle's `postcodes.csv` as `source=import`. Learning (`source=learned`,
from people who give a code and confirm a place) and staff decisions (`source=staff`, through
a ratified suggestion) outrank it, as they already do. A contract with Iran Post is the only
route to "once and for all", and whether to seek one is a decision for the cooperative, not
for this file.

## What to do next, in order

1. **Wikidata aliases.** Have `osm_import.py` keep OSM's `wikidata=Q…` tag on each place.
   Harvest Persian labels, aliases and official names (P1448) for those items, and write the
   ones not already there as `aliases.csv` rows (`kind=old` or `colloquial`). CC0: add
   Wikidata to the manifest's sources and nothing else is owed.
2. **GeoNames villages.** Offer them to the suggestion queue, not the bundle
   (`place.suggestion`, `origin=import`), matched to the nearest place of our tree by
   coordinates. A person confirms each before it becomes a place. CC BY: credit GeoNames on
   the page that credits OSM.
3. **OSM post codes** into `postcodes.csv`, as above.
4. **Bushehr's boundary** from geoBoundaries if the next extract still cuts it.
