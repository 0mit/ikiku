# Part of iKiKu. Licensed under AGPL-3.0.
"""A person may choose to show their neighbourhood (2026-09-18): the reason on the public face
says so. The visibility rows are noupdate data, so a changed reason reaches an existing
database only here; nobody's place changes -- the choice starts off for everyone."""
from odoo import SUPERUSER_ID, api

REASON = "شهرِ شخص، یا محله‌اش اگر خودش خواسته است؛ درشت‌ترین جایی که از او نشان داده می‌شود — بند ۷."


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    row = env.ref('ikiku_base.vis_res_partner_place_public_id', raise_if_not_found=False)
    if row:
        row.reason = REASON
