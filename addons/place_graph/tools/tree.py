# Part of place_graph. Licensed under AGPL-3.0.
"""What a place READS AS and what it is FOUND BY, as plain functions of plain data.

Everything here is worked out from names, kinds and the chain of places above -- never from
a database. That is the point of the file: the same answer is needed in four places, and a
rule written four times is four rules.

  - the model (place.py) computes `path` and `suggest_index` for a row somebody edits;
  - the bundle loader (bundle.py, place_load.py) computes them for a hundred thousand rows
    at once, in seconds, without the ORM;
  - the pipeline outside Odoo checks a bundle before anybody loads it;
  - the responder (services/place_responder) is handed `spec()` and ranks with the very
    same weights, so the answer a person sees does not depend on which door it came through.

The constants are here, once, for the same reason. place.py imports them.
"""
from functools import lru_cache

try:  # inside Odoo
    from odoo.addons.search_suggest.tools import text
except ImportError:  # the pipeline and the tests, outside Odoo
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    '..', '..', 'search_suggest', 'tools'))
    import text  # noqa: E402

KINDS = [
    ('country', "Country"),
    ('province', "Province"),
    ('county', "County"),
    ('city', "City"),
    ('village', "Village"),
    ('district', "District"),
    ('neighbourhood', "Neighbourhood"),
    ('street', "Street"),
    ('other', "Other"),
]
KIND_CODES = tuple(code for code, _label in KINDS)

ALIAS_KINDS = [
    ('old', "Former name"),
    ('colloquial', "What people call it"),
    ('landmark', "Landmark inside it"),
    ('transit', "Metro or bus stop"),
    ('square', "Square or crossing"),
    ('spelling', "Another spelling"),
]
ALIAS_KIND_CODES = tuple(code for code, _label in ALIAS_KINDS)

# How much a text about a place counts, compared with the place's own name (1.0).
#
# A name the place once had, or that people use for it, is nearly its name. A landmark
# INSIDE it is weaker on purpose: a square or a metro stop stands in one place and is named
# for something else, so it should lose to any place actually called that.
ALIAS_WEIGHT = {'old': 0.9, 'colloquial': 0.9, 'spelling': 0.9,
                'square': 0.6, 'transit': 0.6, 'landmark': 0.6}
ALIAS_WEIGHT_DEFAULT = 0.6
PARENT_WEIGHT = 0.35      # «تهران» typed while looking for a neighbourhood of Tehran
NEIGHBOUR_WEIGHT = 0.25   # «ولیعصر» typed by someone who means the street beside it
# The place's own fields, as search_suggest's `_suggest_fields` declares them on the model.
OWN_FIELDS = (('name', 1.0), ('name_en', 0.8), ('code', 0.4))

# How fine each kind is. Only the order matters: it says which kinds are above a place and
# which are below it, so a path can be built without asking how deep the tree happens to be
# in this country -- one has counties and districts, another neither.
FINENESS = {'country': 0, 'province': 1, 'county': 2, 'city': 3, 'village': 3,
            'district': 4, 'neighbourhood': 5, 'street': 6, 'other': 4}
# A path is read out the way an address is said: the place, the area of the city it is in,
# and the city (or, with no city above it, the province). The layers in between are true and
# unsaid -- nobody says «ناحیه ۲» to explain where a café is.
PATH_AREA_KINDS = ('neighbourhood', 'district')
PATH_PLACE_KINDS = ('city', 'village')
PATH_REGION_KINDS = ('province',)
PATH_SEPARATOR = ' · '
PATH_DEPTH = 3   # what a person reads: the place and the two shown places above it
MAX_DEPTH = 12   # how far up a tree is ever walked in one go: country to street is eight

# What a form may offer, by name. A person says which city they work in; a café may name the
# street, because that is what people tell a courier and what a card turns into a
# neighbourhood. «all» leaves out the layers nobody says: a county is in the tree because
# cities hang off it, and «شهرستان دماوند» is not an answer to «where is your café».
PICKER_KINDS = {
    'city': ('city', 'village', 'province'),
    'area': ('neighbourhood', 'district', 'city', 'village'),
    'all': ('street', 'neighbourhood', 'district', 'city', 'village', 'province'),
}
PICKER_DEFAULT = 'all'

# Equal scores keep the published order: the sequence a person set, then the id.
SUGGEST_ORDER = 'sequence, id'


def read_path(own, ancestors):
    """«فلسطین · دانشگاه تهران · تهران»: the place, the part of the city it is in, and the
    city. Not every layer it hangs off -- a path that says every true thing about a place is
    one nobody reads to the end.

    own: (name, kind, in_path). ancestors: the same for every place above, nearest first."""
    name, kind, in_path = own
    parts = [name] if in_path else []
    fineness = FINENESS.get(kind, 4)
    shown = [a for a in ancestors if a[2]]
    for kinds in (PATH_AREA_KINDS, PATH_PLACE_KINDS, PATH_REGION_KINDS):
        if len(parts) >= PATH_DEPTH:
            break
        found = next((a for a in shown if a[1] in kinds and FINENESS.get(a[1], 4) < fineness), None)
        if found and found[0] not in parts:
            parts.append(found[0])
            if kinds is PATH_PLACE_KINDS:
                break          # a city says enough; its province is not needed too
    return PATH_SEPARATOR.join(parts[:PATH_DEPTH])


def suggest_texts(names, name_en, code, aliases, ancestors, neighbours):
    """(field, weight, text) for one place, in the order the model lists them.

    names: the place's name in every installed language (one entry when there is one).
    aliases: (name, kind), in the order the model reads them. ancestors: names, nearest
    first. neighbours: names."""
    texts, seen = [], set()
    for value in names:
        if value and value not in seen:
            seen.add(value)
            texts.append(('name', 1.0, value))
    for field, weight in OWN_FIELDS[1:]:
        value = name_en if field == 'name_en' else code
        if value:
            texts.append((field, weight, value))
    for alias, kind in aliases:
        texts.append(('alias', ALIAS_WEIGHT.get(kind, ALIAS_WEIGHT_DEFAULT), alias))
    for name in ancestors:
        texts.append(('parent', PARENT_WEIGHT, name))
    for name in neighbours:
        texts.append(('neighbour', NEIGHBOUR_WEIGHT, name))
    return texts


def suggest_index(texts):
    """The stored, folded index search_suggest narrows with: every text spaced and compact."""
    out = []
    for _field, _weight, value in texts:
        out.extend(_folded(value))
    return ' '.join(t for t in out if t)


@lru_cache(maxsize=1 << 18)
def _folded(value):
    """(spaced, compact) of one text. Cached because a hundred thousand places repeat the
    same few thousand names above them: «ایران» is folded once, not a hundred thousand times."""
    return text.spaced(value), text.compact(value)


CITY_KINDS = ('city', 'village')


def city_sequence(kind, sequence, ancestors):
    """The first tie-break of equal scores: the sequence of the city or village a place is, or
    is in -- so «فلسطین» in Tehran comes before the one in Rasht, by the same big-cities data
    that orders the cities themselves. A place with no city above it keeps its own sequence.

    ancestors: (kind, sequence) of every place above, nearest first."""
    if kind in CITY_KINDS:
        return sequence
    return next((seq for k, seq in ancestors if k in CITY_KINDS), sequence)


def climb(kind, ancestors, allowed):
    """Where a match answers on a form that offers only `allowed` kinds: the place itself if
    its kind is offered, else the index (into ancestors, nearest first) of the nearest place
    above it that is -- «کاخ» is a street in Tehran and on a form asking for a city it means
    تهران. None when nothing above it is offered, or when the place is not finer than what is.
    Returns 'self' or an int or None."""
    if not allowed or kind in allowed:
        return 'self'
    # Only what is FINER than anything the form offers climbs. A county is coarser than a city:
    # on a form that offers cities it is simply not an answer, and lifting it to its province
    # would put provinces above every city of the same name.
    if FINENESS.get(kind, 4) <= max(FINENESS.get(k, 4) for k in allowed):
        return None
    return next((i for i, (k, active) in enumerate(ancestors) if active and k in allowed), None)


def chain(key, parent_of):
    """The keys above `key`, nearest first, stopping at a cycle or at MAX_DEPTH steps more
    than any real tree has -- a malformed file must not hang a loader."""
    out, seen = [], {key}
    parent = parent_of.get(key)
    while parent is not None and parent not in seen and len(out) < 4 * MAX_DEPTH:
        out.append(parent)
        seen.add(parent)
        parent = parent_of.get(parent)
    return out


def spec():
    """Everything a responder needs to rank exactly as this module does, as plain data.

    Published into the database (ir.config_parameter `place_graph.responder_spec`) and into
    every bundle's manifest, so a responder never carries a weight of its own."""
    return {
        'format': 'place-responder-spec/1',
        'own_fields': [list(pair) for pair in OWN_FIELDS],
        'alias_weight': ALIAS_WEIGHT,
        'alias_weight_default': ALIAS_WEIGHT_DEFAULT,
        'parent_weight': PARENT_WEIGHT,
        'neighbour_weight': NEIGHBOUR_WEIGHT,
        'within_boost': 1.0 + PARENT_WEIGHT,
        'match_kinds': dict(text.MATCH_KINDS),
        'typo_threshold': text.TYPO_THRESHOLD,
        'picker_kinds': {name: list(kinds) for name, kinds in PICKER_KINDS.items()},
        'picker_default': PICKER_DEFAULT,
        'path_separator': PATH_SEPARATOR,
        'order': SUGGEST_ORDER,
        # Equal scores: the city's order first (city_sequence), then the place's, then its id.
        'tie_break': ['city_sequence', 'sequence', 'id'],
        # A match of a kind the form does not offer answers as the nearest offered place above.
        'climb_to_offered_kind': True,
    }
