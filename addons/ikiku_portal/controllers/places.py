# Part of iKiKu. Licensed under AGPL-3.0.
"""Suggesting a place while somebody types it.

/places/suggest?q=&kinds=&within=&quick=

The same question the place responder answers (services/place_responder), with the same answer
shape. The page asks the responder first when one is configured, and this when it is not or
does not answer: the ranking is search_suggest's in both, so a fallback changes the speed and
nothing else.

The tree is public knowledge and names no person (بند ۶), so this answers without a login.
What it will not do is answer with anything but places: no count of who is there, no need,
no business. A café's own place reaches the world through its need's card, where
`place_public_id` decides how fine that may be -- never through here.

`quick=1` is the widget asking for whatever can be answered at once, because the full answer
is taking long enough that an empty list would be the wrong thing to show.
"""
from odoo import http
from odoo.http import request

from odoo.addons.place_graph.tools.tree import KINDS as KIND_CHOICES, PICKER_KINDS as KINDS

SUGGEST_LIMIT = 8
# What a form may ask for is place_graph's PICKER_KINDS -- the same named sets the responder
# is handed in the published spec, so both doors offer the same places.


class IkikuPlaces(http.Controller):

    @http.route('/places/suggest', type='http', auth='public', methods=['GET'], website=True,
                sitemap=False)
    def suggest(self, q=None, kinds='all', within=None, quick=None, **kw):
        query = (q or '').strip()[:80]
        Place = request.env['place.node'].sudo()
        results = []
        if query:
            inside = Place.browse(int(within)).exists() if (within or '').isdigit() else None
            # A named set, or a comma list of kinds -- the same two the responder accepts.
            asked = KINDS.get(kinds) or tuple(k for k in (kinds or '').split(',') if k in dict(KIND_CHOICES)) or None
            found = Place.suggest_places(query, kinds=asked, within=inside,
                                         limit=SUGGEST_LIMIT, widen=not quick)
            for result in found:
                place = result['record']
                results.append({
                    'id': place.id,
                    'code': place.code,
                    'label': place.name,
                    # The path says which of the many places with this name this one is, and
                    # the kind says what it is, so «فلسطین» the street and «فلسطین» the
                    # neighbourhood are told apart before anybody picks the wrong one.
                    'detail': place.path,
                    'kind': place.kind,
                    'score': result['score'],
                    'field': result['field'],
                    'match': result['match'],
                })
                if result.get('via'):
                    # Found through a finer place the form does not offer: say which.
                    results[-1]['via'] = result['via'].name
        return request.make_json_response({'results': results})
