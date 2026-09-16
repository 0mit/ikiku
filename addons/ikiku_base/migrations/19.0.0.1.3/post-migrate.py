# Part of iKiKu. Licensed under AGPL-3.0.
"""The proven number becomes the phone staff see (operator, 2026-09-16).

Every partner with ikiku_mobile gets it in `phone`; a different phone already there is
kept on a child contact «تلفنِ دیگر». Nothing is tracked and no number is logged.
"""
import logging

from odoo import SUPERUSER_ID, api

from odoo.addons.ikiku_base.models.partner import PHONE_SYNC

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {'active_test': False, 'mail_notrack': True, PHONE_SYNC: True})
    partners = env['res.partner'].search([('ikiku_mobile', '!=', False)])
    kept = copied = 0
    for partner in partners:
        if partner.phone == partner.ikiku_mobile:
            continue
        if partner.phone and not partner._ikiku_same_number(partner.phone, partner.ikiku_mobile):
            partner._ikiku_keep_other_phone()
            kept += 1
        partner.write({'phone': partner.ikiku_mobile})
        copied += 1
    policy = env.ref('ikiku_base.vis_res_partner_phone', raise_if_not_found=False)
    if policy:
        policy.reason = "بند ۷: برای حساب‌های ایکیکو همان شمارهٔ ورود است."
    _logger.info("ikiku_base 19.0.0.1.3: phone set from the login number on %d partners, "
                 "%d other phones kept on a child contact", copied, kept)
