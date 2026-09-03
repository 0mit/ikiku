# Part of iKiKu. Licensed under AGPL-3.0.
"""Bookings can be disputed too, so the link is added where booking exists.

It is deliberately NOT in ikiku_base: base must install on its own, and a field
pointing at a model from another module would stop it.
"""
from odoo import fields, models


class IkikuDispute(models.Model):
    _inherit = 'ikiku.dispute'

    booking_id = fields.Many2one('ikiku.booking', string="گمارش", ondelete='cascade')
