# Part of iKiKu. Licensed under AGPL-3.0.
"""From «show my neighbourhood» (a yes/no that lived one morning) to place_visibility (2026-09-18).

A person who said yes keeps their neighbourhood shown; everybody else stays at their city.
Businesses start at their city too -- until now a café's neighbourhood was shown without its
holder being asked, and the operator made that the holder's choice. The reasons on the rows
that changed meaning are rewritten here, because the visibility rows are noupdate data.
"""
from odoo import SUPERUSER_ID, api

REASONS = {
    'ikiku_base.vis_res_partner_place_public_id':
        "شهرِ شخص، یا محله‌اش اگر خودش انتخاب کرده است؛ درشت‌ترین جایی که از او نشان داده می‌شود — بند ۷.",
    'ikiku_base.vis_ikiku_business_place_public_id':
        "شهرِ کسب‌وکار، یا محله‌اش اگر دارنده انتخاب کرده است؛ هرگز خیابان.",
}


def migrate(cr, version):
    if not version:
        return
    cr.execute("SELECT 1 FROM information_schema.columns WHERE table_name = 'res_partner' "
               "AND column_name = 'ikiku_show_neighbourhood'")
    if cr.fetchone():
        cr.execute("UPDATE res_partner SET place_visibility = 'neighbourhood' WHERE ikiku_show_neighbourhood")
        cr.execute("ALTER TABLE res_partner DROP COLUMN ikiku_show_neighbourhood")
    env = api.Environment(cr, SUPERUSER_ID, {})
    old = env.ref('ikiku_base.vis_res_partner_ikiku_show_neighbourhood', raise_if_not_found=False)
    if old:
        old.unlink()
    for xmlid, reason in REASONS.items():
        row = env.ref(xmlid, raise_if_not_found=False)
        if row:
            row.reason = reason
    # People recompute their public face from the choice now in force. Cafés and needs are
    # ikiku_demand's, which loads after this module: its own migration does them.
    people = env['res.partner'].with_context(active_test=False).search([('place_id', '!=', False)])
    people.modified(['place_visibility'])
    env.flush_all()
