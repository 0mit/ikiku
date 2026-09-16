# Part of iKiKu. Licensed under AGPL-3.0.
"""The site's own settings, kept as code so they cannot silently drift.

`_ikiku_setup_site` is called from data/ikiku_site_data.xml, which is NOT
noupdate: it runs on install and again on every `-u ikiku_portal`, so it must be
idempotent. It only touches what iKiKu owns — its menus, the signup door, and
Odoo's placeholder company name — and leaves anything a person has set alone.
"""
import base64

from odoo import api, models
from odoo.tools.misc import file_open

# The two doors in plain words (کی؟ is the worker, کو؟ the business), the open jobs,
# and help. The ledgers and the law moved to the footer on 2026-09-16; the home page
# still shows them. Each entry lists the addresses it had before, so the menu record
# is updated in place rather than duplicated.
IKIKU_MENUS = [
    ('/', 'خانه', 10, ()),
    ('/ki', 'کار می‌خوام', 20, ('/ikiku/ki',)),
    ('/ku', 'همکار می‌خوام', 30, ('/ikiku/ku',)),
    ('/jobs', 'کارهای باز', 40, ('/ikiku/jobs',)),
    ('/help', 'راهنما', 50, ()),
]
# Odoo's contact form mails the company address, and there is none yet. The ledger and
# manifesto entries are in the footer now.
RETIRED_MENU_URLS = ('/contactus', '/ikiku/bookings', '/ikiku/costs', '/ikiku/manifest',
                     '/bookings', '/costs', '/manifest')
PLACEHOLDER_COMPANY_NAMES = ('My Company', 'YourCompany')
# The brand files (2026-09-17). Each replaces an Odoo default only, never an image a person set.
BRAND = {
    'company_logo': 'ikiku_portal/static/src/img/ikiku-horizontal-640.png',
    'website_logo': 'ikiku_portal/static/src/img/ikiku-horizontal.svg',
    'favicon': 'ikiku_portal/static/src/img/favicon.ico',
    'social': 'ikiku_portal/static/src/img/ikiku-social-1200x630.png',
}


def _brand(key):
    with file_open(BRAND[key], 'rb') as f:
        return base64.b64encode(f.read())
SESSION_DAYS = 30


class Website(models.Model):
    _inherit = 'website'

    @api.model
    def _ikiku_setup_site(self):
        company = self.env.ref('base.main_company')
        if company.name in PLACEHOLDER_COMPANY_NAMES:
            company.name = 'ایکیکو'
        if company.uses_default_logo:
            company.logo = _brand('company_logo')
        # Every sign-in by SMS costs a message, so a session lasts 30 days of inactivity
        # (operator, D-3). The parameter is global: staff sessions last as long.
        params = self.env['ir.config_parameter'].sudo()
        if not params.get_param('sessions.max_inactivity_seconds'):
            params.set_param('sessions.max_inactivity_seconds', SESSION_DAYS * 24 * 3600)
        langs = ['en_US'] + (['fa_IR'] if self.env['res.lang'].search_count(
            [('code', '=', 'fa_IR'), ('active', '=', True)]) else [])
        Menu = self.env['website.menu']
        for website in self.search([]):
            # Public email signup is closed (operator, 2026-09-16, D-1 B): people come in
            # with a mobile number and an SMS code at /enter. /web/login stays for staff
            # and for accounts that already use email.
            website.auth_signup_uninvited = 'b2b'
            if website.name in ('My Website', 'Website'):
                website.name = company.name
            if website.favicon == website._default_favicon():
                website.favicon = _brand('favicon')
            if website.logo == website._default_logo():
                website.logo = _brand('website_logo')
            if not website.social_default_image:
                website.social_default_image = _brand('social')
            top = website.menu_id
            if not top:
                continue
            children = top.child_id
            for url, name, sequence, old_urls in IKIKU_MENUS:
                menu = children.filtered(lambda m: m.url == url or m.url in old_urls)[:1]
                if not menu:
                    menu = Menu.create({'name': name, 'url': url, 'parent_id': top.id,
                                        'website_id': website.id, 'sequence': sequence})
                menu.write({'url': url, 'sequence': sequence})
                for lang in langs:
                    menu.with_context(lang=lang).name = name
            children.filtered(lambda m: m.url in RETIRED_MENU_URLS).unlink()
        return True
