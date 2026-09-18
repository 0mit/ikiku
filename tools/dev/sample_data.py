# Part of iKiKu. Licensed under AGPL-3.0.
"""Made-up people and workplaces to look at the site with (tools/dev only; never on a real server).

    docker compose -f tools/dev/compose.yml run --rm -T odoo odoo shell -c /etc/odoo/odoo.conf -d ikiku < tools/dev/sample_data.py

Accounts (password = login + "-pass"): worker «sample-ki», workplace holder «sample-ku».
"""
portal = env.ref('base.group_portal')
Place = env['place.node']


def place(code):
    return Place.search([('code', '=', code)], limit=1)


def user(login, name):
    found = env['res.users'].search([('login', '=', login)])
    return found or env['res.users'].create({'name': name, 'login': login, 'password': login + '-pass',
                                             'group_ids': [(6, 0, [portal.id])]})


worker = user('sample-ki', "نمونه: سارا کارجو")
holder = user('sample-ku', "نمونه: حمید میزبان")
env.ref('ikiku_base.group_ikiku_business').sudo().user_ids = [(4, holder.id)]
holder.partner_id.ikiku_is_verified = True
worker.partner_id.write({'place_id': place('ir-jahanshar').id})
if not env['ikiku.resource'].search([('partner_id', '=', worker.partner_id.id)]):
    env['ikiku.resource'].create({'partner_id': worker.partner_id.id, 'state': 'active'})
Business = env['ikiku.business']
quiet = Business.search([('name', '=', "نمونه: نانوایی آرام")]) or Business.create(
    {'name': "نمونه: نانوایی آرام", 'partner_id': holder.partner_id.id, 'kind': 'bakery',
     'place_id': place('ir-azimieh').id})
busy = Business.search([('name', '=', "نمونه: کافه پرکار")]) or Business.create(
    {'name': "نمونه: کافه پرکار", 'partner_id': holder.partner_id.id, 'kind': 'cafe',
     'place_id': place('ir-tehran-university').id or place('ir-jahanshar').id, 'name_public': True})
barista = env.ref('ikiku_base.spec_barista')
position = env['ikiku.position'].search([('business_id', '=', busy.id)], limit=1) or env['ikiku.position'].create(
    {'name': "باریستا", 'business_id': busy.id, 'spec_node_id': barista.id})
if not env['ikiku.demand'].search([('business_id', '=', busy.id)]):
    env['ikiku.demand'].create({'business_id': busy.id, 'position_id': position.id,
                                'place_id': busy.place_id.id, 'seats': 2, 'state': 'open'})
env.cr.commit()
print("sample data ready: sample-ki / sample-ki-pass, sample-ku / sample-ku-pass")
