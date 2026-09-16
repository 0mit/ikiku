# Part of iKiKu. Licensed under AGPL-3.0.
"""The number a person proves with an SMS code is the phone staff see, search and send
SMS to (operator, 2026-09-16)."""
import importlib.util

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import HttpCase, TransactionCase, tagged
from odoo.tools.misc import file_path

from odoo.addons.ikiku_portal.tests.test_mobile_challenge import MOBILE, OtpSetup

OTHER = '+989351234567'


@tagged('post_install', '-at_install')
class TestPhoneLink(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.staff = env['res.users'].create({
            'name': "همکار", 'login': 'phone-staff',
            'group_ids': [(6, 0, [env.ref('base.group_user').id, env.ref('base.group_partner_manager').id,
                                  env.ref('ikiku_base.group_ikiku_staff').id])]})

    def partner(self, **vals):
        return self.env['res.partner'].create(dict({'name': "نیرو"}, **vals))

    def test_the_number_fills_the_phone(self):
        partner = self.partner(ikiku_mobile=MOBILE)
        self.assertEqual((partner.phone, partner.phone_sanitized), (MOBILE, MOBILE))

    def test_changing_or_releasing_the_number_moves_the_phone(self):
        partner = self.partner(ikiku_mobile=MOBILE)
        partner.write({'ikiku_mobile': OTHER})
        self.assertEqual(partner.phone, OTHER)
        self.assertFalse(partner.child_ids, "the old number is not kept as another phone")
        partner.write({'ikiku_mobile': False})
        self.assertFalse(partner.phone)

    def test_staff_account_and_number_change_follow(self):
        self.env['ikiku.staff.account'].with_user(self.staff).create(
            {'name': "رضا", 'mobile': '۰۹۱۲۱۲۳۴۵۶۷', 'role': 'ki'}).action_create()
        partner = self.env['res.partner'].search([('ikiku_mobile', '=', MOBILE)])
        self.assertEqual((partner.phone, partner.ikiku_mobile_state), (MOBILE, 'staff'))
        partner.write({'ikiku_mobile_verified_on': fields.Datetime.now()})
        self.assertEqual(partner.ikiku_mobile_state, 'proven')
        self.env['ir.config_parameter'].sudo().set_param('ikiku.nid_salt', 'test-salt')
        partner.ikiku_nid_hash = partner.hash_national_id('0012345678')
        self.env['ikiku.mobile.change'].with_user(self.staff).create(
            {'partner_id': partner.id, 'new_mobile': '09351234567', 'national_id': '0012345678'}).action_apply()
        self.assertEqual((partner.phone, partner.ikiku_mobile), (OTHER, OTHER))
        self.assertFalse(self.env['res.partner'].search([('phone', '=', MOBILE)]))

    def test_the_phone_cannot_drift_from_the_number(self):
        partner = self.partner(ikiku_mobile=MOBILE)
        with self.assertRaises(UserError):
            partner.with_user(self.staff).write({'phone': '02188888888'})
        with self.assertRaises(UserError):
            partner.with_user(self.staff).write({'phone': False})
        partner.with_user(self.staff).write({'phone': '۰۹۱۲۱۲۳۴۵۶۷'})
        self.assertEqual(partner.phone, MOBILE, "the same number in another spelling keeps the stored form")
        ordinary = self.partner(name="مخاطب")
        (partner | ordinary).with_user(self.staff).write({'phone': '09121234567'})
        self.assertEqual((partner.phone, ordinary.phone), (MOBILE, '09121234567'))

    def test_an_ordinary_contact_phone_is_free(self):
        contact = self.partner(name="تامین‌کننده", phone='02188888888')
        contact.with_user(self.staff).write({'phone': '02177777777'})
        self.assertEqual(contact.phone, '02177777777')

    def test_a_person_cannot_change_their_own_phone(self):
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': "خود", 'login': 'phone-self', 'group_ids': [(6, 0, [self.env.ref('base.group_portal').id])]})
        user.partner_id.write({'ikiku_mobile': MOBILE})
        with self.assertRaises(UserError):
            user.partner_id.with_user(user).write({'phone': OTHER})

    def test_only_the_tools_write_the_login_number(self):
        partner = self.partner()
        with self.assertRaises(AccessError):
            partner.with_user(self.staff).write({'ikiku_mobile': MOBILE})
        with self.assertRaises(AccessError):
            self.env['res.partner'].with_user(self.staff).create({'name': "x", 'ikiku_mobile': MOBILE})

    def test_a_landline_is_kept_on_a_child_contact(self):
        partner = self.partner(phone='02188888888')
        partner.write({'ikiku_mobile': MOBILE})
        self.assertEqual(partner.phone, MOBILE)
        self.assertEqual(partner.child_ids.mapped('phone'), ['02188888888'])
        self.assertEqual(partner.child_ids.name, "تلفنِ دیگر")

    def test_the_phone_is_not_tracked(self):
        self.assertFalse(self.env['res.partner']._fields['phone'].tracking)
        partner = self.partner(ikiku_mobile=MOBILE)
        partner.write({'ikiku_mobile': OTHER})
        partner.write({'ikiku_mobile': False})
        values = self.env['mail.tracking.value'].sudo().search([('mail_message_id.res_id', '=', partner.id),
                                                                ('mail_message_id.model', '=', 'res.partner')])
        text = ' '.join(partner.message_ids.mapped('body')) + ' '.join(
            str(v.old_value_char) + str(v.new_value_char) for v in values)
        self.assertNotIn('9121234567', text)
        self.assertNotIn('9351234567', text)

    def test_sms_reaches_the_proven_number(self):
        partner = self.partner(ikiku_mobile=MOBILE)
        composer = self.env['sms.composer'].with_context(active_model='res.partner', active_id=partner.id).create(
            {'body': "سلام"})
        self.assertEqual(composer.recipient_single_number_itf, MOBILE)

    def test_staff_find_a_person_by_how_they_say_the_number(self):
        partner = self.partner(ikiku_mobile=MOBILE)
        Partner = self.env['res.partner'].with_user(self.staff)
        for typed in ('09121234567', '۰۹۱۲۱۲۳۴۵۶۷', '+989121234567'):
            self.assertEqual(Partner.search([('ikiku_mobile_lookup', '=', typed)]), partner, typed)
        self.assertFalse(Partner.search([('ikiku_mobile_lookup', '=', 'نه')]))

    def test_the_contact_form_loads_for_staff_and_others(self):
        plain = self.env['res.users'].create({'name': "کارمند", 'login': 'phone-plain',
                                              'group_ids': [(6, 0, [self.env.ref('base.group_user').id])]})
        staff_arch = self.env['res.partner'].with_user(self.staff).get_views([(False, 'form')])['views']['form']['arch']
        plain_arch = self.env['res.partner'].with_user(plain).get_views([(False, 'form')])['views']['form']['arch']
        self.assertIn('ikiku_mobile_state', staff_arch)
        self.assertNotIn('ikiku_mobile_state', plain_arch)

    def test_staff_account_asks_before_adopting_a_contact(self):
        contact = self.partner(name="رضا", phone='09121234567')
        Account = self.env['ikiku.staff.account'].with_user(self.staff)
        wizard = Account.create({'name': "رضا", 'mobile': '09121234567', 'role': 'ki'})
        self.assertEqual(wizard.existing_partner_ids, contact)
        with self.assertRaises(UserError):
            wizard.action_create()
        wizard.match_action = 'adopt'
        wizard.action_create()
        self.assertEqual((contact.ikiku_mobile, contact.phone), (MOBILE, MOBILE))
        self.assertTrue(self.env['ikiku.resource'].search([('partner_id', '=', contact.id)]))

    def test_a_call_back_request_shows_the_account(self):
        partner = self.partner(ikiku_mobile=MOBILE)
        request = self.env['ikiku.help.request'].create({'name': "رضا", 'mobile': '۰۹۱۲۱۲۳۴۵۶۷', 'best_time': 'noon'})
        self.assertEqual(request.matched_partner_id, partner)
        self.assertFalse(self.env['ikiku.help.request'].create(
            {'name': "x", 'mobile': 'نمی‌دونم', 'best_time': 'noon'}).matched_partner_id)

    def test_the_migration_copies_and_keeps(self):
        spec = importlib.util.spec_from_file_location(
            'ikiku_base_post_migrate_19_0_0_1_3', file_path('ikiku_base/migrations/19.0.0.1.3/post-migrate.py'))
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        landline = self.partner(name="با تلفن", ikiku_mobile=MOBILE)
        plain = self.partner(name="بی تلفن", ikiku_mobile=OTHER)
        self.env.cr.execute("UPDATE res_partner SET phone = '02188888888' WHERE id = %s", [landline.id])
        self.env.cr.execute("UPDATE res_partner SET phone = NULL WHERE id = %s", [plain.id])
        self.env.invalidate_all()
        migration.migrate(self.env.cr, '19.0.0.1.2')
        self.env.invalidate_all()
        self.assertEqual((landline.phone, plain.phone), (MOBILE, OTHER))
        self.assertEqual(landline.child_ids.mapped('phone'), ['02188888888'])


@tagged('post_install', '-at_install')
class TestPhoneOnPages(OtpSetup, HttpCase):

    def test_my_pages_show_the_masked_number(self):
        portal = self.env.ref('base.group_portal')
        user = self.env['res.users'].create({'name': "سارا", 'login': 'phone-page', 'password': 'phone-page-pass-1',
                                             'group_ids': [(6, 0, [portal.id])]})
        user.partner_id.write({'ikiku_mobile': MOBILE, 'ikiku_mobile_verified_on': fields.Datetime.now()})
        user.partner_id._ikiku_grant_role('ki')
        user.partner_id._ikiku_grant_role('ku', business_name="کافه")
        self.authenticate('phone-page', 'phone-page-pass-1')
        for url in ('/me', '/business'):
            page = self.url_open(url).text
            self.assertIn('۰۹۱۲•••۴۵۶۷', page, url)
            self.assertIn("تأیید شده", page, url)
            self.assertNotIn('9121234567', page, url)
            self.assertNotIn('۹۱۲۱۲۳۴۵۶۷', page, url)

    def test_help_names_the_number_once(self):
        dide = self.url_open('/help/dide').text
        self.assertEqual(dide.count("شماره موبایل"), 1)
        self.assertNotIn(">تلفن<", dide)
