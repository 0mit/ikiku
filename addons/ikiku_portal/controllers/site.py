# Part of iKiKu. Licensed under AGPL-3.0.
"""The front door: the name's two questions, and the law they come from.

کی؟ is who — a worker. کو؟ is where — a business. Each door explains what
happens next and hands over to Odoo's own signup or login with a redirect into
the matching join flow, so the account and the role are made in one visit.
A visitor who is already signed in walks straight through.
"""
import re
from markupsafe import Markup, escape

from odoo import http
from odoo.http import request
from odoo.tools.misc import file_path

from odoo.addons.ikiku_portal.controllers.auth import SIDE_HOME, SIDE_START, ikiku_sides

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


# Renamed screens; every other old /ikiku/... path maps to the same path without the prefix.
RENAMED = {
    'join/verify': 'enter/code',
    'join/availability': 'join/when',
    'business/position/new': 'business/need/who',
}


class IkikuSite(http.Controller):

    def _door(self, template, role):
        user = request.env.user
        if not user._is_public():
            if not user.share:
                return request.redirect('/odoo')
            sides = ikiku_sides(user)
            if role in sides:
                return request.redirect(SIDE_HOME[role])
            if sides:
                # Holding the other side: ask before a second one is made.
                return request.render('ikiku_portal.door_add_%s' % role, {})
            return request.redirect(SIDE_START[role])
        return request.render(template, {
            'start_url': '/enter?as=%s' % role,
            'otp_enabled': request.env.company._sms_otp_ready(),
        })

    @http.route('/ki', type='http', auth='public', website=True)
    def door_ki(self, **kw):
        return self._door('ikiku_portal.door_ki', 'ki')

    @http.route('/ku', type='http', auth='public', website=True)
    def door_ku(self, node=None, **kw):
        """`node` comes from a role shortcut on the home page: the first question of the
        business flow opens with that role already chosen."""
        chosen = request.env['ikiku.spec.node'].sudo().browse(
            int(node) if node and str(node).isdigit() else 0).exists()
        if chosen and chosen.kind == 'competency':
            request.session['ikiku_need'] = {'node_id': chosen.id}
        return self._door('ikiku_portal.door_ku', 'ku')

    @http.route('/manifest', type='http', auth='public', website=True)
    def manifest(self, **kw):
        with open(file_path(MANIFEST_PATH), encoding='utf-8') as f:
            body = render_manifest(f.read())
        return request.render('ikiku_portal.manifest_page', {'body': body})

    @http.route(['/ikiku', '/ikiku/<path:rest>'], type='http', auth='public', website=True, sitemap=False)
    def old_address(self, rest='', **kw):
        """The site lived under /ikiku/ until 2026-09-16; ikiku.ir/ikiku/... said the name twice.
        Old links, bookmarks and shared pages keep working through a permanent redirect."""
        rest = rest.strip('/')
        target = '/' + RENAMED.get(rest, rest)
        query = request.httprequest.query_string.decode()
        return request.redirect(target + ('?' + query if query else ''), code=301, local=True)
