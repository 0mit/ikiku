# Part of iKiKu. Licensed under AGPL-3.0.
"""The register's reader («خوانندهٔ دفتر»): an account that reads what the staff read and writes nothing.

A reader outside Odoo -- a program holding an API key, or a person who only looks -- needs the
staff's eyes without their hands, so that a key that leaks can change nothing. The group reads
every model the staff group reads, the wizards aside (they hold nothing to read), and the
staff-only fields the staff's screens show. It never reads the national number's hash or a
mobile challenge's secrets, and Odoo's own back office offers it no button it cannot press.
The staff keep everything they had."""
import io
import json
from datetime import date, datetime, timedelta

from lxml import etree

from odoo.exceptions import AccessError, UserError
from odoo.tests import HttpCase, TransactionCase, get_db_name, tagged

READER = 'ikiku_base.group_ikiku_register_reader'
STAFF = 'ikiku_base.group_ikiku_staff'
# A person's staff-only fields that no staff screen shows stay the staff's alone: the national
# number's hash above all (partner.py: the most stealable thing the co-op could own), the day
# the card was checked, and which colleague wrote a number.
PARTNER_STAFF_ONLY = {'ikiku_nid_hash', 'ikiku_nid_checked_on', 'ikiku_mobile_set_by_id'}
# What the staff's partner screens show of the login number: the badge, the search by number,
# and the two filters on whether the SIM's owner proved it.
PARTNER_SCREEN = {'ikiku_mobile_state', 'ikiku_mobile_lookup', 'ikiku_mobile_verified_on'}
# The menus that open a staff wizard: tools for acting, not for reading.
WIZARD_MENUS = ('ikiku_portal.menu_ikiku_staff_account', 'ikiku_portal.menu_ikiku_staff_role',
                'ikiku_portal.menu_ikiku_mobile_change')


def place(env, name, kind='city'):
    found = env['place.node'].sudo().search([('kind', '=', kind), ('name', '=', name)], limit=1)
    assert found, "place_ir has no %s called %s" % (kind, name)
    return found


def jpeg():
    from PIL import Image
    out = io.BytesIO()
    Image.new('RGB', (32, 24), (90, 140, 60)).save(out, format='JPEG')
    return out.getvalue()


def staff_models(env):
    """Every model the staff group reads by an access row of its own, the wizards aside."""
    rows = env['ir.model.access'].sudo().search([('group_id', '=', env.ref(STAFF).id), ('perm_read', '=', True)])
    return sorted({row.model_id.model for row in rows if not env[row.model_id.model]._transient})


def make_user(env, login, group):
    return env['res.users'].with_context(no_reset_password=True).create({
        'name': login, 'login': login, 'group_ids': [(6, 0, [env.ref(group).id])]})


def make_register(cls):
    """Invented records on every screen the staff use, one or more of each."""
    env = cls.env
    env['ir.config_parameter'].set_param('ikiku.nid_salt', 'register-reader-test')
    tehran = place(env, "تهران")
    node = env.ref('ikiku_base.spec_dishwashing')
    cls.person = env['res.partner'].create({'name': "خوانده‌شده", 'ikiku_mobile': '+989121110000'})
    cls.person.ikiku_nid_hash = cls.person.hash_national_id('0012345678')
    holder = env['res.partner'].create({'name': "دارندهٔ کافه"})
    cls.business = env['ikiku.business'].create({'name': "کافه دفتر", 'partner_id': holder.id,
                                                 'place_id': tehran.id})
    position = env['ikiku.position'].create({'name': "ظرف‌شور", 'business_id': cls.business.id,
                                             'spec_node_id': node.id})
    cls.need = env['ikiku.demand'].create({'business_id': cls.business.id, 'position_id': position.id,
                                           'place_id': tehran.id, 'seats': 1})
    cls.open_need = env['ikiku.demand'].create({'business_id': cls.business.id, 'position_id': position.id,
                                                'place_id': tehran.id, 'seats': 2, 'state': 'open'})
    cls.free_need = env['ikiku.demand'].create({'business_id': cls.business.id, 'position_id': position.id,
                                                'place_id': tehran.id, 'seats': 1, 'state': 'open'})
    cls.resource = env['ikiku.resource'].create({'partner_id': cls.person.id})
    env['ikiku.availability'].create({'resource_id': cls.resource.id, 'place_id': tehran.id})
    cls.proposal = env['ikiku.proposal'].create({'demand_id': cls.open_need.id, 'resource_id': cls.resource.id})
    cls.booking = env['ikiku.booking'].create({'demand_id': cls.open_need.id, 'resource_id': cls.resource.id})
    cls.photo = env['ikiku.photo'].ikiku_add(jpeg(), partner=cls.person)
    cls.call = env['ikiku.help.request'].create({'name': "کسی که گیر کرده", 'mobile': '09121110000'})
    cls.challenge = env['ikiku.mobile.challenge'].create({'mobile': '+989121110000', 'code_hash': 'f' * 64,
                                                          'pending_code': '123456'})
    cls.assertion = env['ikiku.assertion'].create({
        'resource_id': cls.person.id, 'asserted_by_id': cls.person.id, 'claim_kind': 'skill',
        'spec_node_id': node.id})
    env['ikiku.favorite'].ikiku_join(env['res.partner'].create({'name': "در صف"}), cls.business)
    cls.period = env['ikiku.cost.period'].create({
        'name': "دورهٔ آزمون", 'date_start': date.today() - timedelta(days=30), 'date_end': date.today(),
        'currency_id': env.company.currency_id.id, 'total_cost': 1000})


@tagged('post_install', '-at_install')
class TestRegisterReader(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.reader = make_user(cls.env, 'register-reader', READER)
        cls.staff = make_user(cls.env, 'register-staff', STAFF)
        make_register(cls)
        cls.models = staff_models(cls.env)

    def test_the_group_is_an_internal_user_and_nothing_more(self):
        group = self.env.ref(READER)
        self.assertEqual(group.implied_ids, self.env.ref('base.group_user'))
        self.assertFalse(self.reader.has_group(STAFF))
        self.assertTrue(self.reader._is_internal())
        rows = self.env['ir.model.access'].search([('group_id', '=', group.id)])
        self.assertEqual(sorted(set(rows.model_id.mapped('model'))), self.models,
                         "read rows on exactly the models the staff read, the wizards aside")
        for row in rows:
            with self.subTest(row=row.name):
                self.assertEqual((row.perm_read, row.perm_write, row.perm_create, row.perm_unlink),
                                 (True, False, False, False))
        self.assertIn('ikiku.help.request', self.models)
        self.assertIn('ikiku.cost.share', self.models)
        self.assertNotIn('ikiku.mobile.change', self.models)

    def test_it_reads_every_staff_model_as_the_staff_do(self):
        for model in self.models:
            with self.subTest(model=model):
                as_reader, as_staff = self.env[model].with_user(self.reader), self.env[model].with_user(self.staff)
                fields = as_reader.fields_get(attributes=['type'])
                self.assertEqual(set(fields), set(as_staff.fields_get(attributes=['type'])),
                                 "every field the staff read on %s" % model)
                rows = as_reader.search_read([], list(fields), order='id')
                self.assertEqual([row['id'] for row in rows], as_staff.search([], order='id').ids)
        self.assertEqual(self.photo.with_user(self.reader).state, 'pending')
        self.assertEqual(self.call.with_user(self.reader).mobile, '09121110000')

    def test_it_writes_nothing(self):
        for model in self.models:
            for operation in ('create', 'write', 'unlink'):
                with self.subTest(model=model, operation=operation), self.assertRaises(AccessError):
                    self.env[model].with_user(self.reader).check_access(operation)
        writes = [(self.need, {'seats': 9}), (self.business, {'name': "دیگر"}), (self.resource, {'headline': "x"}),
                  (self.call, {'state': 'closed'}), (self.photo, {'reject_reason': "x"}),
                  (self.period, {'total_cost': 1}), (self.booking, {'state': 'cancelled'}),
                  (self.proposal, {'state': 'rejected'}), (self.assertion, {'state': 'contested'}),
                  (self.challenge, {'state': 'expired'})]
        for record, vals in writes:
            with self.subTest(write=record._name), self.assertRaises(AccessError):
                record.with_user(self.reader).write(vals)
            with self.subTest(unlink=record._name), self.assertRaises(AccessError):
                record.with_user(self.reader).unlink()
        with self.assertRaises(AccessError):
            self.env['ikiku.help.request'].with_user(self.reader).create({'name': "x", 'mobile': '09120000000'})
        for wizard in ('ikiku.demand.cancel', 'ikiku.staff.account', 'ikiku.staff.role', 'ikiku.mobile.change'):
            with self.subTest(wizard=wizard), self.assertRaises(AccessError):
                self.env[wizard].with_user(self.reader).check_access('create')
        self.assertEqual((self.need.seats, self.call.state, self.photo.state), (1, 'new', 'pending'))

    def test_every_button_refuses_it(self):
        """What the back-office buttons call, called by the reader: each refused, nothing changed.
        (A refused request rolls back whole; the savepoint does here what the request does there.)"""
        presses = [(self.need, 'action_open'), (self.free_need, 'action_ikiku_mark_filled'),
                   (self.proposal, 'action_accept'), (self.photo, 'action_approve'),
                   (self.photo, 'action_reject'), (self.resource, 'action_submit'),
                   (self.resource, 'action_activate'), (self.period, 'action_allocate'),
                   (self.call, 'action_called'), (self.call, 'action_close')]
        for record, method in presses:
            before = record.read(['state'])[0]['state']
            # refused by the access rows (AccessError) or by the method's own check: both are UserError
            with self.subTest(button=method), self.assertRaises(UserError), self.env.cr.savepoint():
                getattr(record.with_user(self.reader), method)()
            record.invalidate_recordset()
            self.assertEqual(record.state, before, "%s changed nothing" % method)

    def test_it_reads_what_the_staff_screens_show_of_a_person(self):
        Partner = self.env['res.partner'].with_user(self.reader)
        self.assertEqual(self.person.with_user(self.reader).ikiku_mobile_state, 'unproven')
        self.assertEqual(Partner.search([('ikiku_mobile_lookup', '=', '۰۹۱۲۱۱۱۰۰۰۰')]), self.person,
                         "found by the number, however it is typed")
        unproven = [('ikiku_mobile', '!=', False), ('ikiku_mobile_verified_on', '=', False)]
        self.assertIn(self.person, Partner.search(unproven), "the screen's filter «شمارهٔ ورودِ تأییدنشده»")
        staff_fields = set(self.env['res.partner'].with_user(self.staff).fields_get(attributes=['type']))
        reader_fields = set(Partner.fields_get(attributes=['type']))
        self.assertEqual(staff_fields - reader_fields, PARTNER_STAFF_ONLY)
        self.assertLessEqual(PARTNER_SCREEN, reader_fields)

    def test_never_the_hash_or_a_challenges_secrets(self):
        person = self.person.with_user(self.reader)
        for name in PARTNER_STAFF_ONLY:
            with self.subTest(field=name), self.assertRaises(AccessError):
                person.read([name])
        with self.assertRaises(AccessError):
            self.env['res.partner'].with_user(self.reader).search([('ikiku_nid_hash', '!=', False)])
        Challenge = self.env['ikiku.mobile.challenge']
        secrets = {name for name, field in Challenge._fields.items() if field.groups == 'base.group_system'}
        self.assertLessEqual({'code_hash', 'pending_code', 'session_key', 'login_token_hash'}, secrets)
        challenge = self.challenge.with_user(self.reader)
        self.assertFalse(secrets & set(challenge.read()[0]), "a whole read leaves them out")
        for name in secrets:
            with self.subTest(field=name), self.assertRaises(AccessError):
                challenge.read([name])
        self.assertEqual(challenge.mobile, '+989121110000', "the rest of the challenge is read")

    def test_its_menus_open_what_it_reads_and_no_wizard(self):
        Menu = self.env['ir.ui.menu']
        visible = Menu.with_user(self.reader)._visible_menu_ids()
        for xmlid in ('ikiku_portal.menu_ikiku_help_request', 'ikiku_base.menu_ikiku_spec_node',
                      'ikiku_supply.menu_ikiku_resource', 'ikiku_demand.menu_ikiku_photo', 'ikiku_coop.menu_ikiku_coop'):
            with self.subTest(menu=xmlid):
                self.assertIn(self.env.ref(xmlid).id, visible)
        for xmlid in WIZARD_MENUS + ('ikiku_base.menu_ikiku_config',):
            with self.subTest(menu=xmlid):
                self.assertNotIn(self.env.ref(xmlid).id, visible)
        for_staff = Menu.with_user(self.staff)._visible_menu_ids()
        for xmlid in WIZARD_MENUS + ('ikiku_portal.menu_ikiku_help_request',):
            self.assertIn(self.env.ref(xmlid).id, for_staff, "the staff keep their tools")

    def test_the_staff_as_before(self):
        self.assertTrue(self.staff.has_group(STAFF))
        self.assertFalse(self.staff.has_group(READER), "a staff member is not made a reader")
        self.call.with_user(self.staff).action_called()
        self.assertEqual(self.call.state, 'called')
        self.photo.with_user(self.staff).action_approve()
        self.assertEqual(self.photo.state, 'approved')
        self.assertEqual(self.person.with_user(self.staff).ikiku_nid_hash, self.person.hash_national_id('0012345678'))


@tagged('post_install', '-at_install')
class TestRegisterReaderOverJson2(HttpCase):
    """The way an outside reader asks: Odoo 19's JSON-2, with the reader's own API key."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.reader = make_user(cls.env, 'register-reader-key', READER)
        make_register(cls)
        key = cls.env['res.users.apikeys'].with_user(cls.reader)._generate(
            scope='rpc', name="register reader (test)", expiration_date=datetime.now() + timedelta(hours=12))
        cls.headers = {'Content-Type': 'application/json', 'Authorization': 'bearer ' + key,
                       'X-Odoo-Database': get_db_name()}

    def ask(self, model, method, **body):
        return self.url_open('/json/2/%s/%s' % (model, method), data=json.dumps(body), headers=self.headers)

    def test_it_counts_and_reads_and_is_refused_a_write(self):
        counted = self.ask('ikiku.help.request', 'search_count', domain=[('state', '=', 'new')])
        self.assertEqual(counted.status_code, 200, counted.text)
        self.assertEqual(counted.json(), self.env['ikiku.help.request'].search_count([('state', '=', 'new')]))
        unproven = self.ask('res.partner', 'search_count',
                            domain=[('ikiku_mobile', '!=', False), ('ikiku_mobile_verified_on', '=', False)])
        self.assertEqual(unproven.status_code, 200, unproven.text)
        self.assertGreaterEqual(unproven.json(), 1)
        refused = self.ask('ikiku.help.request', 'write', ids=self.call.ids, vals={'state': 'closed'})
        self.assertEqual(refused.status_code, 403, refused.text)
        pressed = self.ask('ikiku.help.request', 'action_called', ids=self.call.ids)
        self.assertEqual(pressed.status_code, 403, pressed.text)
        hashed = self.ask('res.partner', 'read', ids=self.person.ids, fields=['ikiku_nid_hash'])
        self.assertEqual(hashed.status_code, 403, hashed.text)
        self.call.invalidate_recordset()
        self.assertEqual(self.call.state, 'new')
