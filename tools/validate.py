#!/usr/bin/env python3
"""Static checks for the iKiKu addons, for use where Odoo cannot be booted.

It does NOT replace an install. It catches the four mistakes that are cheap to
make and expensive to find: a manifest naming a file that is not there, an ACL
naming a model nobody declared, a view naming a field the model does not have,
and a model with no ACL at all (which loads fine and then denies everyone).
"""
import ast
import csv
import os
import re
import sys
import xml.etree.ElementTree as ET

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'addons')
FIELD_RE = re.compile(
    r'^\s{4}(\w+)\s*=\s*fields\.(\w+)\(\s*(?:["\']([\w.]+)["\'])?', re.M)
NAME_RE = re.compile(r"^\s*_name\s*=\s*['\"]([\w.]+)['\"]", re.M)
INHERIT_RE = re.compile(r"^\s*_inherit\s*=\s*(.+)$", re.M)

# Fields Odoo adds to every model, or that mixins we use contribute.
BUILTIN = {
    'id', 'display_name', 'create_date', 'create_uid', 'write_date', 'write_uid',
    '__last_update', 'activity_ids', 'message_ids', 'message_follower_ids',
    'message_partner_ids', 'message_attachment_count', 'rating_ids', 'active',
    'sequence', 'company_id', 'currency_id', 'name',
}
# hr.individual.skill.mixin contributes these to ikiku.resource.skill.
MIXIN_FIELDS = {
    'hr.individual.skill.mixin': {'skill_id', 'skill_level_id', 'skill_type_id',
                                  'level_progress', 'color', 'valid_from', 'valid_to'},
    'mail.thread': {'message_ids', 'message_follower_ids'},
}

errors, warnings = [], []


def modules():
    for name in sorted(os.listdir(ROOT)):
        path = os.path.join(ROOT, name)
        if os.path.isfile(os.path.join(path, '__manifest__.py')):
            yield name, path


RELATIONAL = {'Many2one', 'One2many', 'Many2many'}


def collect_models():
    """model name -> set(fields), following _inherit chains within our addons."""
    models, inherits = {}, {}
    RELATIONAL = {'Many2one', 'One2many', 'Many2many'}
    for _mod, path in modules():
        for dirpath, _dirs, files in os.walk(path):
            for fn in files:
                if not fn.endswith('.py'):
                    continue
                src = open(os.path.join(dirpath, fn), encoding='utf-8').read()
                for block in re.split(r'\nclass ', src)[1:]:
                    found = {}
                    for fname, ftype, comodel in FIELD_RE.findall('\n' + block):
                        found[fname] = comodel if ftype in RELATIONAL else None
                    m = NAME_RE.search(block)
                    inh = INHERIT_RE.search(block)
                    inh_names = re.findall(r"['\"]([\w.]+)['\"]", inh.group(1)) if inh else []
                    target = m.group(1) if m else (inh_names[0] if inh_names else None)
                    if not target:
                        continue
                    models.setdefault(target, {}).update(found)
                    inherits.setdefault(target, set()).update(inh_names)
    # pull mixin-contributed fields in
    for model, parents in inherits.items():
        for parent in parents:
            models[model].update({f: None for f in MIXIN_FIELDS.get(parent, set())})
            if parent in models and parent != model:
                models[model].update(models[parent])
    return models


def check_manifest_files():
    for mod, path in modules():
        src = open(os.path.join(path, '__manifest__.py'), encoding='utf-8').read()
        manifest = ast.literal_eval(src)
        for rel in manifest.get('data', []):
            if not os.path.isfile(os.path.join(path, rel)):
                errors.append("%s: manifest lists missing file %s" % (mod, rel))
        for bundle in manifest.get('assets', {}).values():
            for asset in bundle:
                rel = asset.split('/', 1)[1]
                if not os.path.isfile(os.path.join(path, rel)):
                    errors.append("%s: asset missing %s" % (mod, asset))
        if manifest.get('license') != 'AGPL-3':
            errors.append("%s: license is %r, expected AGPL-3" % (mod, manifest.get('license')))


def check_acls(models):
    acl_models = set()
    for mod, path in modules():
        csv_path = os.path.join(path, 'security', 'ir.model.access.csv')
        if not os.path.isfile(csv_path):
            continue
        with open(csv_path, encoding='utf-8') as fh:
            for row in csv.DictReader(fh):
                ref = row['model_id:id']
                if not ref.startswith('model_'):
                    continue
                guess = ref[len('model_'):].replace('_', '.')
                # ikiku.booking.check <- model_ikiku_booking_check
                matches = [m for m in models if m.replace('.', '_') == ref[len('model_'):]]
                if not matches:
                    errors.append("%s: ACL %s refers to unknown model (%s?)"
                                  % (mod, row['id'], guess))
                else:
                    acl_models.add(matches[0])
    for model in models:
        if model.startswith('ikiku.') and model not in acl_models:
            if model in ('ikiku.publishable',):   # abstract, no table
                continue
            warnings.append("model %s has no ACL row -- nobody can read it" % model)


def _walk(node, model, models, where):
    """Fields belong to the model of the subview they sit in, not the root."""
    known = models.get(model)
    for child in node:
        if child.tag == 'field' and child.get('name'):
            fname = child.get('name')
            if known is not None and fname not in known and fname not in BUILTIN:
                warnings.append("%s: <field name=\"%s\"> not on %s" % (where, fname, model))
            comodel = (known or {}).get(fname)
            if len(child):                       # a nested subview
                _walk(child, comodel or model, models, where)
        else:
            _walk(child, model, models, where)


def check_view_fields(models):
    for mod, path in modules():
        vdir = os.path.join(path, 'views')
        if not os.path.isdir(vdir):
            continue
        for fn in sorted(os.listdir(vdir)):
            if not fn.endswith('.xml'):
                continue
            tree = ET.parse(os.path.join(vdir, fn))
            for rec in tree.iter('record'):
                if rec.get('model') != 'ir.ui.view':
                    continue
                model_el = rec.find("./field[@name='model']")
                arch = rec.find("./field[@name='arch']")
                if model_el is None or arch is None or not model_el.text:
                    continue
                model = model_el.text.strip()
                if model not in models:
                    warnings.append("%s/%s: view for unknown model %s" % (mod, fn, model))
                    continue
                _walk(arch, model, models, "%s/%s" % (mod, fn))


def main():
    models = collect_models()
    check_manifest_files()
    check_acls(models)
    check_view_fields(models)
    print("models declared: %d" % len([m for m in models if m.startswith('ikiku.')]))
    for w in warnings:
        print("  WARN  %s" % w)
    for e in errors:
        print("  ERROR %s" % e)
    print("\n%d error(s), %d warning(s)" % (len(errors), len(warnings)))
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
