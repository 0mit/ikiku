# Part of iKiKu. Licensed under AGPL-3.0.
"""The site's own settings, kept as code so they cannot silently drift.

`_ikiku_setup_site` is called from data/ikiku_site_data.xml, which is NOT
noupdate: it runs on install and again on every `-u ikiku_portal`, so it must be
idempotent. It only touches what iKiKu owns — its menus, the signup door, and
Odoo's placeholder company name — and leaves anything a person has set alone.
"""
from odoo import api, models

# The two questions of the name are the two doors: کی؟ is who (a worker),
# کو؟ is where (a business). The rest are the public ledgers and the law.
IKIKU_MENUS = [
    ('/', 'خانه', 10),
    ('/ikiku/ki', 'کی؟', 20),
    ('/ikiku/ku', 'کو؟', 30),
    ('/ikiku/jobs', 'کارهای باز', 40),
    ('/ikiku/bookings', 'دفترِ تعهدها', 50),
    ('/ikiku/costs', 'هزینهٔ مشترک', 60),
    ('/ikiku/manifest', 'مرام‌نامه', 70),
]
# Odoo's contact form mails the company address, and there is none yet.
RETIRED_MENU_URLS = ('/contactus',)
PLACEHOLDER_COMPANY_NAMES = ('My Company', 'YourCompany')
SESSION_DAYS = 30


class Website(models.Model):
    _inherit = 'website'

    @api.model
    def _ikiku_setup_site(self):
        company = self.env.ref('base.main_company')
        if company.name in PLACEHOLDER_COMPANY_NAMES:
            company.name = 'ایکیکو'
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
            top = website.menu_id
            if not top:
                continue
            children = top.child_id
            for url, name, sequence in IKIKU_MENUS:
                menu = children.filtered(lambda m: m.url == url)[:1]
                if not menu:
                    menu = Menu.create({'name': name, 'url': url, 'parent_id': top.id,
                                        'website_id': website.id, 'sequence': sequence})
                menu.sequence = sequence
                for lang in langs:
                    menu.with_context(lang=lang).name = name
            children.filtered(lambda m: m.url in RETIRED_MENU_URLS).unlink()
        return True
