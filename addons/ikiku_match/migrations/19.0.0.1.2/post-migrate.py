# Part of iKiKu. Licensed under AGPL-3.0.
"""One person may hold a business and look for work (operator, 2026-09-16).

A business gets a place of its own from its needs where it only had its holder's, and
any booking of a holder at their own business is flagged for staff, never cancelled.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    filled, detached = env['ikiku.business']._ikiku_place_from_needs()
    flagged = env['ikiku.booking']._ikiku_flag_own_bookings()
    _logger.info("ikiku_match 19.0.0.1.2: %d businesses given a place, %d moved off their holder's home, "
                 "%d own-business bookings flagged", filled, detached, len(flagged))
