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
        """Write PROVINCE_ORDER into `sequence`. Runs on install only, from noupdate data, so
        an order staff set afterwards is left alone."""
        places = self.with_context(active_test=False)
        for position, name in enumerate(PROVINCE_ORDER, start=1):
            found = places.search([('kind', '=', 'province'), ('name', '=', name)])
            if not found:
                continue
            found.sequence = position
        return True
