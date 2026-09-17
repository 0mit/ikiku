# Part of iKiKu. Licensed under AGPL-3.0.
"""The standard, read by anyone: roles, the skills they need, and the knowledge under them.

/roles                          every role on offer here, by family, with a search box
/roles/<code>                   what the work is, the skills it needs, its ISCO-08 occupation
/skills/<code>                  what the skill is, the roles that use it, the fields it draws on
/knowledge                      the fields of knowledge (ISCED-F 2013) and occupations (ISCO-08)
/knowledge/<scheme>/<code>      one field or occupation: its parts, and what rests on it
/standard/suggest?q=&kind=      suggestions as the person types (search_suggest)

The standard is public by design (بند ۶): it names work, never a person. Nodes a country
rule withholds (alcohol in Iran) answer 404 here and never appear in lists or suggestions.
"""
from collections import defaultdict

from odoo import http
from odoo.http import request

from odoo.addons.ikiku_base.models.jalali import to_fa_digits
from odoo.addons.ikiku_base.models.spec import SUGGEST_ORDER
from odoo.addons.ikiku_portal.controllers.portal import subgroups

SUGGEST_LIMIT = 8
IMPORTANCE_ORDER = ('core', 'common', 'specialist')
IMPORTANCE_TITLE = {
    'core': "اصلی",
    'common': "معمولاً لازمه",
    'specialist': "برای کارِ تخصصی‌تر",
}
KIND_LABEL = {'role': "کار", 'competency': "مهارت"}
SCHEMES = {'isced-f-2013': 'field', 'isco-08': 'occupation'}


class IkikuStandard(http.Controller):

    # ----------------------------------------------------------------- helpers
    def _nodes(self):
        return request.env['ikiku.spec.node'].sudo()

    def _hidden(self):
        if not hasattr(request, '_ikiku_hidden_nodes'):
            request._ikiku_hidden_nodes = set(self._nodes().ikiku_hidden_ids())
        return request._ikiku_hidden_nodes

    def _offered(self, records):
        hidden = self._hidden()
        return records.filtered(lambda node: node.id not in hidden)

    def _node(self, code, kind):
        node = self._nodes().search([('code', '=', code), ('kind', '=', kind)], limit=1)
        return node if node and node.id not in self._hidden() else None

    def _label(self, node):
        return node.plain_label or node.name

    def _trail(self, node):
        """The families above a node, root first, without the root itself."""
        trail = []
        parent = node.parent_id
        while parent and parent.parent_id:
            trail.insert(0, parent)
            parent = parent.parent_id
        return trail

    def _link_counts(self, relation):
        """Links per knowledge class, with each count rolled up to every ancestor."""
        Link = request.env['ikiku.knowledge.link'].sudo()
        hidden = self._hidden()
        direct = defaultdict(set)
        for link in Link.search([('relation', '=', relation)]):
            if link.node_id.id not in hidden:
                direct[link.class_id].add(link.node_id.id)
        total = defaultdict(set)
        for klass, node_ids in direct.items():
            for ancestor_id in (int(part) for part in (klass.parent_path or '').split('/') if part):
                total[ancestor_id] |= node_ids
        return {class_id: len(ids) for class_id, ids in total.items()}

    # ------------------------------------------------------------------- roles
    @http.route('/roles', type='http', auth='public', website=True)
    def roles(self, q=None, **kw):
        Node = self._nodes()
        root = request.env.ref('ikiku_base.spec_fnb')
        query = (q or '').strip()[:80]
        results = []
        if query:
            domain = [('kind', '=', 'role')] + Node.ikiku_offered_domain()
            results = [r['record'] for r in Node.suggest(query, domain=domain, limit=20, order=SUGGEST_ORDER)]
        families = []
        for family in Node.search([('kind', '=', 'family'), ('parent_id', '=', root.id)], order='sequence, id'):
            roles = self._offered(Node.search([('kind', '=', 'role'), ('parent_id', 'child_of', family.id)],
                                              order='sequence, id'))
            if roles:
                others = roles.filtered(lambda r: not r.featured)
                families.append({'family': family, 'featured': roles.filtered('featured'),
                                 'others': others, 'parts': subgroups(others, family),
                                 'count': to_fa_digits(len(roles))})
        return request.render('ikiku_portal.standard_roles', {
            'families': families, 'query': query, 'results': results,
            'total': to_fa_digits(sum(len(f['featured']) + len(f['others']) for f in families)),
        })

    @http.route('/roles/<string:code>', type='http', auth='public', website=True)
    def role(self, code, **kw):
        role = self._node(code, 'role')
        if not role:
            return request.not_found()
        hidden = self._hidden()
        groups = []
        for importance in IMPORTANCE_ORDER:
            skills = role.requirement_ids.filtered(
                lambda req: req.importance == importance and req.skill_id.id not in hidden).mapped('skill_id')
            if skills:
                groups.append((IMPORTANCE_TITLE[importance], skills.sorted(lambda s: self._label(s))))
        occupations = role.knowledge_link_ids.filtered(lambda link: link.relation == 'classified_as').mapped('class_id')
        return request.render('ikiku_portal.standard_role', {
            'role': role, 'label': self._label(role), 'trail': self._trail(role), 'groups': groups,
            'occupations': occupations,
        })

    # ------------------------------------------------------------------ skills
    @http.route('/skills/<string:code>', type='http', auth='public', website=True)
    def skill(self, code, **kw):
        skill = self._node(code, 'competency')
        if not skill:
            return request.not_found()
        roles = self._offered(skill.used_by_ids.mapped('role_id')).sorted(lambda r: self._label(r))
        links = skill.knowledge_link_ids.filtered(lambda link: link.relation == 'draws_on')
        return request.render('ikiku_portal.standard_skill', {
            'skill': skill, 'label': self._label(skill), 'trail': self._trail(skill), 'roles': roles,
            'links': links.sorted(lambda link: link.class_id.code),
        })

    # --------------------------------------------------------------- knowledge
    @http.route('/knowledge', type='http', auth='public', website=True)
    def knowledge(self, q=None, **kw):
        Class = request.env['ikiku.knowledge.class'].sudo()
        query = (q or '').strip()[:80]
        results = [r['record'] for r in Class.suggest(query, limit=20)] if query else []
        schemes = []
        for scheme_code, relation, noun in (('isced-f-2013', 'draws_on', "مهارت"), ('isco-08', 'classified_as', "کار")):
            scheme = request.env['ikiku.knowledge.scheme'].sudo().search([('code', '=', scheme_code)], limit=1)
            if not scheme:
                continue
            counts = self._link_counts(relation)
            tops = Class.search([('scheme_id', '=', scheme.id), ('parent_id', '=', False)])
            schemes.append({'scheme': scheme, 'noun': noun, 'tops': [
                {'klass': top, 'count': counts.get(top.id, 0), 'count_fa': to_fa_digits(counts.get(top.id, 0))}
                for top in tops]})
        return request.render('ikiku_portal.standard_knowledge', {'schemes': schemes, 'query': query,
                                                                  'results': results})

    @http.route('/knowledge/<string:scheme_code>/<string:code>', type='http', auth='public', website=True)
    def knowledge_class(self, scheme_code, code, **kw):
        if scheme_code not in SCHEMES:
            return request.not_found()
        klass = request.env['ikiku.knowledge.class'].sudo().search(
            [('scheme_id.code', '=', scheme_code), ('code', '=', code)], limit=1)
        if not klass:
            return request.not_found()
        relation = 'draws_on' if SCHEMES[scheme_code] == 'field' else 'classified_as'
        counts = self._link_counts(relation)
        hidden = self._hidden()
        links = klass.link_ids.filtered(lambda link: link.relation == relation and link.node_id.id not in hidden)
        by_node = defaultdict(list)
        for link in links:
            by_node[link.node_id].append(link)
        ancestors = request.env['ikiku.knowledge.class'].sudo().browse(
            [int(part) for part in (klass.parent_path or '').split('/') if part][:-1])
        return request.render('ikiku_portal.standard_knowledge_class', {
            'klass': klass, 'scheme_code': scheme_code, 'ancestors': ancestors,
            'children': [{'klass': child, 'count': counts.get(child.id, 0),
                          'count_fa': to_fa_digits(counts.get(child.id, 0))} for child in klass.child_ids],
            'rows': sorted(by_node.items(), key=lambda item: self._label(item[0])),
            'total_fa': to_fa_digits(counts.get(klass.id, 0)),
            'noun': "مهارت" if relation == 'draws_on' else "کار",
        })

    # ----------------------------------------------------------------- suggest
    @http.route('/standard/suggest', type='http', auth='public', methods=['GET'], website=True, sitemap=False)
    def suggest(self, q=None, kind='role', quick=None, **kw):
        query = (q or '').strip()[:80]
        # quick=1: the widget asking for whatever can be answered at once, because the full
        # answer is taking long enough that an empty list is the wrong thing to be showing.
        widen = not quick
        results = []
        if query and kind in ('role', 'skill', 'knowledge'):
            if kind == 'knowledge':
                for found in request.env['ikiku.knowledge.class'].sudo().suggest(
                        query, limit=SUGGEST_LIMIT, widen=widen):
                    klass = found['record']
                    results.append({'id': klass.id, 'label': klass.name,
                                    'detail': "%s · %s" % (klass.code, klass.name_en),
                                    'url': '/knowledge/%s/%s' % (klass.scheme_id.code, klass.code)})
            else:
                node_kind = 'role' if kind == 'role' else 'competency'
                Node = self._nodes()
                domain = [('kind', '=', node_kind)] + Node.ikiku_offered_domain()
                for found in Node.suggest(query, domain=domain, limit=SUGGEST_LIMIT,
                                          order=SUGGEST_ORDER, widen=widen):
                    node = found['record']
                    family = node.parent_id
                    detail = self._label(family) if family else ''
                    if node.plain_label and node.name and node.plain_label != node.name:
                        detail = "%s · %s" % (node.name, detail) if detail else node.name
                    results.append({'id': node.id, 'label': self._label(node), 'detail': detail,
                                    'url': '/%s/%s' % ('roles' if node_kind == 'role' else 'skills', node.code)})
        return request.make_json_response({'results': results})
