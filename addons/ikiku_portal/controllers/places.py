# Part of iKiKu. Licensed under AGPL-3.0.
"""Suggesting a place while somebody types it.

/places/suggest?q=&kinds=&within=&quick=

The tree is public knowledge and names no person (بند ۶), so this answers without a login.
What it will not do is answer with anything but places: no count of who is there, no need,
no business. A café's own place reaches the world through its need's card, where
`place_public_id` decides how fine that may be -- never through here.

`quick=1` is the widget asking for whatever can be answered at once, because the full answer
is taking long enough that an empty list would be the wrong thing to show.
"""
from odoo import http
from odoo.http import request

SUGGEST_LIMIT = 8
# What a form may ask for. A person says which city they work in; a café may name the
# street, because that is what people tell a courier and what a card turns into a
# neighbourhood. Anything else is «all».
KINDS = {
    'city': ('city', 'village', 'province'),
    'area': ('neighbourhood', 'district', 'city', 'village'),
    'all': None,
}


class IkikuPlaces(http.Controller):

    @http.route('/places/suggest', type='http', auth='public', methods=['GET'], website=True,
                sitemap=False)
    def suggest(self, q=None, kinds='all', within=None, quick=None, **kw):
        query = (q or '').strip()[:80]
        Place = request.env['place.node'].sudo()
        results = []
        if query:
            inside = Place.browse(int(within)).exists() if (within or '').isdigit() else None
            found = Place.suggest_places(query, kinds=KINDS.get(kinds, None), within=inside,
                                         limit=SUGGEST_LIMIT, widen=not quick)
            for result in found:
                place = result['record']
                results.append({
                    'id': place.id,
                    'label': place.name,
                    # The path says which of the many places with this name this one is, and
                    # the kind says what it is, so «فلسطین» the street and «فلسطین» the
                    # neighbourhood are told apart before anybody picks the wrong one.
                    'detail': place.path,
                    'kind': place.kind,
                })
        return request.make_json_response({'results': results})
