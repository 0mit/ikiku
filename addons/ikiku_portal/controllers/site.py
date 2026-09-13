# Part of iKiKu. Licensed under AGPL-3.0.
"""The front door: the name's two questions, and the law they come from.

کی؟ is who — a worker. کو؟ is where — a business. Each door explains what
happens next and hands over to Odoo's own signup or login with a redirect into
the matching join flow, so the account and the role are made in one visit.
A visitor who is already signed in walks straight through.
"""
import re
from urllib.parse import urlencode

from markupsafe import Markup, escape

from odoo import http
from odoo.http import request
from odoo.tools.misc import file_path

# The مرام‌نامه the site publishes. tools/validate.py fails the build if this
# copy is not byte-identical to docs/MANIFEST.fa.md, which is the law.
MANIFEST_PATH = 'ikiku_portal/data/MANIFEST.fa.md'


def _inline(text):
    html = str(escape(text))
    html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
    html = re.sub(r'(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])', r'<em>\1</em>', html)
    return html


def render_manifest(markdown):
    """The small subset of Markdown the مرام‌نامه uses: headings, rules, lists,
    paragraphs, bold and italics. Everything is escaped before it is marked up."""
    out, para, items = [], [], []

    def flush():
        if para:
            out.append('<p>%s</p>' % '<br/>'.join(_inline(line) for line in para))
            para.clear()
        if items:
            out.append('<ul>%s</ul>' % ''.join('<li>%s</li>' % _inline(i) for i in items))
            items.clear()

    for raw in markdown.splitlines():
        line = raw.strip()
        heading = re.match(r'^(#{1,3})\s+(.*)$', line)
        if not line:
            flush()
        elif heading:
            flush()
            level = len(heading.group(1))
            out.append('<h%d>%s</h%d>' % (level, _inline(heading.group(2)), level))
        elif line == '---':
            flush()
            out.append('<hr/>')
        elif line.startswith('- '):
            if para:
                flush()
            items.append(line[2:])
        else:
            if items:
                flush()
            para.append(line)
    flush()
    return Markup('\n'.join(out))


class IkikuSite(http.Controller):

    def _door(self, template, next_url):
        if not request.env.user._is_public():
            return request.redirect(next_url)
        return request.render(template, {
            'signup_enabled': request.env['res.users'].sudo()._get_signup_invitation_scope() == 'b2c',
            'signup_url': '/web/signup?' + urlencode({'redirect': next_url}),
            'login_url': '/web/login?' + urlencode({'redirect': next_url}),
        })

    @http.route('/ikiku/ki', type='http', auth='public', website=True)
    def door_ki(self, **kw):
        partner = request.env.user.partner_id
        has_record = not request.env.user._is_public() and request.env['ikiku.resource'].sudo().search_count(
            [('partner_id', '=', partner.id)], limit=1)
        return self._door('ikiku_portal.door_ki', '/ikiku/me' if has_record else '/ikiku/join')

    @http.route('/ikiku/ku', type='http', auth='public', website=True)
    def door_ku(self, **kw):
        partner = request.env.user.partner_id.commercial_partner_id
        has_record = not request.env.user._is_public() and request.env['ikiku.business'].sudo().search_count(
            [('partner_id', '=', partner.id)], limit=1)
        return self._door('ikiku_portal.door_ku',
                          '/ikiku/business' if has_record else '/ikiku/business/position/new')

    @http.route('/ikiku/manifest', type='http', auth='public', website=True)
    def manifest(self, **kw):
        with open(file_path(MANIFEST_PATH), encoding='utf-8') as f:
            body = render_manifest(f.read())
        return request.render('ikiku_portal.manifest_page', {'body': body})
