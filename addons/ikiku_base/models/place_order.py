# Part of iKiKu. Licensed under AGPL-3.0.
"""The order Iran's provinces are offered in, and the places portal accounts may read.

The tree comes from place_ir, which is data about the world and says nothing about how a
form should offer it. Two things belong to iKiKu and are therefore here:

  - the order. Tehran first, as the operator asked, then Persian alphabetical -- which the
    database cannot produce on its own, because it sorts گ, ک, پ and چ by code point, after
    the Arabic letters, so گیلان would land after مازندران.
  - who may read a place. The tree is public knowledge (بند ۶); portal accounts read it so a
    form can offer it, and only staff may change it.
"""
from odoo import api, models

# What a list of places puts first, and therefore what wins when two places score the same.
# Ordering is DATA, not a rule inside the ranking: the score says how well a name matches, and
# `sequence` says which of two equally good matches a person more likely meant. Both are
# readable, and بند ۸ is satisfied because neither is learned from behaviour.
#
# By kind: a city called «اندیشه» comes before a street called «اندیشه», because somebody
# saying only «اندیشه» means the town far more often than one road in another town.
KIND_ORDER = {
    'country': 1, 'province': 40, 'city': 100, 'district': 130,
    'neighbourhood': 150, 'village': 170, 'street': 190, 'county': 220, 'other': 200,
}
# The cities people name most, in order of how many live there. A city on this list comes
# before every other city; the list is short on purpose -- it is not a ranking of places, only
# an answer to «which تهران did they mean» for the handful of names that repeat everywhere.
BIG_CITIES = (
    "تهران", "مشهد", "اصفهان", "کرج", "شیراز", "تبریز", "قم", "اهواز", "کرمانشاه", "ارومیه",
    "رشت", "زاهدان", "کرمان", "همدان", "یزد", "اردبیل", "بندرعباس", "اراک", "اسلام‌شهر",
    "زنجان", "سنندج", "قزوین", "خرم‌آباد", "گرگان", "ساری", "شهریار", "قدس", "کاشان",
    "دزفول", "خرمشهر", "بروجرد", "نیشابور", "سبزوار", "بابل", "آمل", "پاکدشت", "ورامین",
    "ملارد", "اندیشه", "بومهن", "پردیس", "شهریار", "نجف‌آباد", "بجنورد", "بیرجند", "بوشهر",
    "ایلام", "شهرکرد", "یاسوج", "سمنان", "خوی", "مراغه", "میاندوآب", "ماهشهر", "آبادان",
)

# Tehran first, then Persian alphabetical. Matched by name against place_ir's provinces.
PROVINCE_ORDER = (
    "استان تهران", "استان آذربایجان شرقی", "استان آذربایجان غربی", "استان اردبیل",
    "استان اصفهان", "استان البرز", "استان ایلام", "استان بوشهر",
    "استان چهارمحال و بختیاری", "استان خراسان جنوبی", "استان خراسان رضوی",
    "استان خراسان شمالی", "استان خوزستان", "استان زنجان", "استان سمنان",
    "استان سیستان و بلوچستان", "استان فارس", "استان قزوین", "استان قم", "استان کردستان",
    "استان کرمان", "استان کرمانشاه", "استان کهگیلویه و بویر احمد", "استان گلستان",
    "استان گیلان", "استان لرستان", "استان مازندران", "استان مرکزی", "استان هرمزگان",
    "استان همدان", "استان یزد",
)


class PlaceNode(models.Model):
    _inherit = 'place.node'

    @api.model
    def _ikiku_apply_province_order(self):
        """Write PROVINCE_ORDER into `sequence`. Runs once, from noupdate data, so an order
        staff set afterwards is left alone."""
        places = self.with_context(active_test=False)
        for position, name in enumerate(PROVINCE_ORDER, start=1):
            found = places.search([('kind', '=', 'province'), ('name', '=', name)])
            if not found:
                continue
            found.sequence = position
        return True

    @api.model
    def _ikiku_apply_place_order(self):
        """Write KIND_ORDER and BIG_CITIES into `sequence`, then the provinces on top of both.

        Runs once, from noupdate data. Everything gets the sequence of its kind; the cities
        people name most get theirs; the provinces keep the order the operator asked for."""
        places = self.with_context(active_test=False)
        for kind, sequence in KIND_ORDER.items():
            rows = places.search([('kind', '=', kind)])
            if rows:
                rows.sequence = sequence
        for position, name in enumerate(BIG_CITIES, start=1):
            rows = places.search([('kind', 'in', ('city', 'village')), ('name', '=', name)])
            if rows:
                rows.sequence = KIND_ORDER['province'] + position
        return self._ikiku_apply_province_order()
