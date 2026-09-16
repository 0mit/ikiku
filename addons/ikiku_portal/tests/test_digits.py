# Part of iKiKu. Licensed under AGPL-3.0.
"""Digits are typed in Persian or Arabic and stored in Latin. On 2026-09-16 a mobile
typed on a Persian keyboard was stripped to nothing by [0-9] and refused."""
from odoo.tests import TransactionCase, tagged

from odoo.addons.ikiku_base.models.jalali import to_latin_digits
from odoo.addons.ikiku_portal.controllers.portal import _int, _parse_jalali


@tagged('post_install', '-at_install')
class TestDigits(TransactionCase):

    def test_converter(self):
        self.assertEqual(to_latin_digits('۰۱۲۳۴۵۶۷۸۹ ٠١٢٣٤٥٦٧٨٩ 0123'), '0123456789 0123456789 0123')
        self.assertIsNone(to_latin_digits(None))
        self.assertIs(to_latin_digits(False), False)

    def test_mobile_in_any_digits(self):
        Partner = self.env['res.partner']
        for typed in ('۰۹۱۲۱۲۳۴۵۶۷', '٠٩١٢١٢٣٤٥٦٧', '۰۹۱۲ ۱۲۳ ۴۵۶۷', '+۹۸۹۱۲۱۲۳۴۵۶۷', '09121234567'):
            self.assertEqual(Partner.normalise_mobile(typed), '+989121234567', typed)

    def test_national_id_in_any_digits(self):
        self.env['ir.config_parameter'].sudo().set_param('ikiku.nid_salt', 'test-salt')
        Partner = self.env['res.partner']
        self.assertEqual(Partner.hash_national_id('۰۰۱۲۳۴۵۶۷۸'), Partner.hash_national_id('0012345678'))

    def test_jalali_dates_in_any_digits(self):
        self.assertEqual(_parse_jalali('۱۴۰۵/۰۹/۰۱'), _parse_jalali('1405/09/01'))
        self.assertEqual(_parse_jalali(' ۱۴۰۵-۰۹-۰۱ '), _parse_jalali('1405/09/01'))
        self.assertEqual(_parse_jalali('۱۴۰۵.۰۹.۰۱'), _parse_jalali('1405/09/01'))
        self.assertFalse(_parse_jalali('فردا'))

    def test_numbers_never_raise(self):
        self.assertEqual(_int('۳'), 3)
        self.assertEqual(_int(' ٤٠ '), 40)
        self.assertEqual(_int('سه', 1), 1)
        self.assertIsNone(_int(None))

    def test_sms_code_in_any_digits(self):
        Challenge = self.env['ikiku.mobile.challenge']
        partner = self.env['res.partner'].create({'name': "رقم"})
        challenge = Challenge.create({'partner_id': partner.id, 'mobile': '+989121234567',
                                      'code_hash': Challenge._hash('123456'), 'state': 'sent'})
        challenge.expires_at = challenge.create_date.replace(year=challenge.create_date.year + 1)
        self.assertFalse(challenge.check('١٢٣٤٥٦'))
