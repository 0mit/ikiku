# Part of iKiKu. Licensed under AGPL-3.0.
from datetime import timedelta
from unittest.mock import patch

import requests
from urllib3.exceptions import MaxRetryError, NewConnectionError

from odoo import fields
from odoo.tests import TransactionCase, tagged

from odoo.addons.sms.tools.sms_api import SmsApi
from odoo.addons.sms_smsir.tools.smsir import SmsIrClient, SmsIrError, local_mobile

PACK = '5b8e4d1c-2a3f-4e6b-9c7d-0f1e2d3c4b5a'


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload, self.status_code = payload, status_code

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def answer(data, status=1, message="موفق"):
    return FakeResponse({'status': status, 'message': message, 'data': data}, 200 if status == 1 else 400)


def like_to_like_echo(special=None):
    """Answer the way sms.ir does: a pack id and one message id per mobile, in order.
    `special` maps a mobile to the id given instead (None refused, 0 blacklisted)."""
    counter = iter(range(9000000, 10000000))
    special = special or {}

    def request(method, url, json=None, headers=None, timeout=None):
        return answer({'packId': PACK, 'cost': 1.0, 'messageIds': [
            special[mobile] if mobile in special else next(counter) for mobile in json['mobiles']]})
    return request


@tagged('post_install', '-at_install')
class TestSmsIrClient(TransactionCase):

    def test_header_json_and_timeout(self):
        with patch.object(requests.Session, 'request',
                          return_value=answer({'packId': PACK, 'messageIds': [7], 'cost': 1.0})) as request:
            SmsIrClient('KEY123').send_like_to_like('30007732', ['09121234567'], ['سلامِ آزمایشی'])
        self.assertEqual(request.call_args.args, ('POST', 'https://api.sms.ir/v1/send/likeToLike'))
        kwargs = request.call_args.kwargs
        self.assertEqual(kwargs['headers']['X-API-KEY'], 'KEY123')
        self.assertEqual(kwargs['json'], {'lineNumber': 30007732, 'mobiles': ['09121234567'],
                                          'messageTexts': ['سلامِ آزمایشی']})
        self.assertEqual(kwargs['timeout'], 30)

    def test_refusal_is_an_error(self):
        # The answer api.sms.ir gave an invalid key on 2026-09-15.
        refused = FakeResponse({'data': None, 'status': 10, 'message': "کلید وب سرویس نامعتبر است"}, 401)
        with patch.object(requests.Session, 'request', return_value=refused):
            with self.assertRaises(SmsIrError) as caught:
                SmsIrClient('BAD').credit()
        self.assertEqual((caught.exception.status, caught.exception.maybe_sent), (10, False))

    def test_whether_a_failed_request_may_have_been_sent(self):
        refused = requests.exceptions.ConnectionError(
            MaxRetryError(None, '/v1/send/likeToLike', NewConnectionError(None, "refused")))
        cases = [
            (requests.exceptions.ConnectTimeout(), False),
            (refused, False),
            (requests.exceptions.SSLError(), False),
            (requests.exceptions.ReadTimeout(), True),
            (requests.exceptions.ConnectionError("Connection aborted."), True),
        ]
        for error, maybe_sent in cases:
            with patch.object(requests.Session, 'request', side_effect=error):
                with self.assertRaises(SmsIrError) as caught:
                    SmsIrClient('KEY').send_like_to_like('3000', ['09121234567'], ['x'])
            self.assertEqual((caught.exception.status, caught.exception.maybe_sent), (0, maybe_sent),
                             type(error).__name__)
        with patch.object(requests.Session, 'request', return_value=FakeResponse(ValueError("<html>"), 502)):
            with self.assertRaises(SmsIrError) as caught:
                SmsIrClient('KEY').send_like_to_like('3000', ['09121234567'], ['x'])
        self.assertTrue(caught.exception.maybe_sent)

    def test_iranian_mobiles_as_sms_ir_writes_them(self):
        for number in ('+989121234567', '00989121234567', '989121234567', '09121234567', '9121234567',
                       '+98 912 123 4567', '۰۹۱۲۱۲۳۴۵۶۷'):
            self.assertEqual(local_mobile(number), '09121234567', number)

    def test_refused_numbers_are_named(self):
        self.assertTrue(SmsIrError('/send/verify', 104, "x").bad_number)
        self.assertFalse(SmsIrError('/send/verify', 20, "x").bad_number)


@tagged('post_install', '-at_install')
class TestSmsIrSending(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.write({'sms_smsir_enabled': True, 'sms_smsir_api_key': 'KEY', 'sms_smsir_line': '30007732'})

    def make_sms(self, count=1, body="کدِ آزمایشی"):
        return self.env['sms.sms'].create([
            {'number': '+98912%07d' % i, 'body': body} for i in range(count)])

    def send_answered(self, response, count=1):
        sms = self.make_sms(count)
        option = 'side_effect' if isinstance(response, Exception) else 'return_value'
        with patch.object(requests.Session, 'request', **{option: response}):
            sms.send(unlink_failed=False, unlink_sent=False)
        return sms

    def test_smsir_is_used_and_iap_is_not(self):
        sms = self.make_sms()
        tracker = self.env['sms.tracker'].create({'sms_uuid': sms.uuid})
        with patch.object(SmsApi, '_contact_iap', side_effect=AssertionError("IAP was contacted")), \
                patch.object(requests.Session, 'request', side_effect=like_to_like_echo()) as request:
            sms.send(unlink_sent=False)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(request.call_args.kwargs['json']['mobiles'], ['09120000000'])
        self.assertEqual(sms.state, 'pending')
        self.assertEqual((tracker.smsir_messageid, tracker.smsir_pack_id, tracker.smsir_company_id),
                         ('9000000', PACK, self.company))

    def test_batches_of_one_hundred(self):
        sms = self.make_sms(250)
        with patch.object(requests.Session, 'request', side_effect=like_to_like_echo()) as request:
            sms.send(unlink_sent=False)
        self.assertEqual([len(c.kwargs['json']['mobiles']) for c in request.call_args_list], [100, 100, 50])
        self.assertEqual(set(sms.mapped('state')), {'pending'})

    def test_refused_and_blacklisted_numbers(self):
        sms = self.make_sms(3)
        echo = like_to_like_echo({'09120000000': None, '09120000001': 0})
        with patch.object(requests.Session, 'request', side_effect=echo):
            sms.send(unlink_failed=False, unlink_sent=False)
        self.assertEqual({s.number: (s.state, s.failure_type) for s in sms}, {
            '+989120000000': ('error', 'sms_number_format'),
            '+989120000001': ('error', 'unknown'),
            '+989120000002': ('pending', False),
        })

    def test_no_credit(self):
        sms = self.send_answered(answer(None, 102, "اعتبار کافی نیست"), count=2)
        self.assertEqual(set(sms.mapped('failure_type')), {'sms_credit'})

    def test_bad_key(self):
        sms = self.send_answered(FakeResponse({'data': None, 'status': 10, 'message': "نامعتبر"}, 401))
        self.assertEqual((sms.state, sms.failure_type), ('error', 'smsir_account'))

    def test_no_answer_may_have_been_sent(self):
        sms = self.send_answered(requests.exceptions.ReadTimeout())
        self.assertEqual((sms.state, sms.failure_type), ('error', 'smsir_unconfirmed'))

    def test_unreachable_sent_nothing(self):
        sms = self.send_answered(requests.exceptions.ConnectTimeout())
        self.assertEqual((sms.state, sms.failure_type), ('error', 'sms_server'))

    def test_an_answer_that_cannot_be_matched_is_unconfirmed(self):
        sms = self.send_answered(answer({'packId': PACK, 'messageIds': [1], 'cost': 1.0}), count=2)
        self.assertEqual(set(sms.mapped('failure_type')), {'smsir_unconfirmed'})

    def test_missing_line(self):
        self.company.sms_smsir_line = False
        sms = self.make_sms()
        with patch.object(requests.Session, 'request') as request:
            sms.send(unlink_failed=False, unlink_sent=False)
        request.assert_not_called()
        self.assertEqual((sms.state, sms.failure_type), ('error', 'smsir_sender'))

    def test_disabled_company_keeps_iap(self):
        self.company.sms_smsir_enabled = False
        sms = self.make_sms()
        with patch.object(SmsApi, '_send_sms_batch', return_value=[{'uuid': sms.uuid, 'state': 'success'}]) as iap, \
                patch.object(requests.Session, 'request', side_effect=AssertionError("sms.ir was contacted")):
            sms.send(unlink_sent=False)
        iap.assert_called_once()


@tagged('post_install', '-at_install')
class TestSmsIrDelivery(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.write({'sms_smsir_enabled': True, 'sms_smsir_api_key': 'KEY', 'sms_smsir_line': '30007732'})
        partner = cls.env['res.partner'].create({'name': "گیرنده"})
        message = partner.message_post(body="x", message_type='sms')
        cls.notification = cls.env['mail.notification'].create({
            'mail_message_id': message.id, 'res_partner_id': partner.id,
            'notification_type': 'sms', 'notification_status': 'pending'})
        cls.tracker = cls.env['sms.tracker'].create({
            'sms_uuid': 'a' * 32, 'mail_notification_id': cls.notification.id,
            'smsir_messageid': '8792343', 'smsir_pack_id': PACK, 'smsir_state': 0,
            'smsir_company_id': cls.company.id, 'smsir_sent_at': fields.Datetime.now()})

    def test_states(self):
        self.tracker._smsir_apply_state(1)
        self.assertEqual(self.notification.notification_status, 'sent')
        other = self.env['res.partner'].create({'name': "گیرندهٔ دوم"})
        notification = self.notification.copy({'res_partner_id': other.id, 'notification_status': 'pending'})
        tracker = self.tracker.copy({'sms_uuid': 'b' * 32, 'mail_notification_id': notification.id})
        tracker._smsir_apply_state(2)
        self.assertEqual((notification.notification_status, notification.failure_type),
                         ('exception', 'sms_not_delivered'))

    def test_polling(self):
        stale = self.tracker.copy({'sms_uuid': 'c' * 32, 'smsir_messageid': '1',
                                   'smsir_sent_at': fields.Datetime.now() - timedelta(hours=49)})
        report = answer([{'messageId': 8792343, 'mobile': 9121234567, 'deliveryState': 1}])
        with patch.object(requests.Session, 'request', return_value=report) as request:
            self.env['sms.tracker']._smsir_poll_status()
        self.assertEqual(request.call_count, 1)
        self.assertEqual(request.call_args.args, ('GET', 'https://api.sms.ir/v1/send/pack/%s' % PACK))
        self.assertEqual(self.tracker.smsir_state, 1)
        self.assertEqual(stale.smsir_state, 0)

    def test_polling_stops_when_sms_ir_cannot_be_reached(self):
        self.tracker.copy({'sms_uuid': 'd' * 32, 'smsir_messageid': '2',
                           'smsir_pack_id': '0b8e4d1c-2a3f-4e6b-9c7d-0f1e2d3c4b5a'})
        with patch.object(requests.Session, 'request', side_effect=requests.exceptions.ConnectTimeout()) as request:
            self.env['sms.tracker']._smsir_poll_status()
        self.assertEqual(request.call_count, 1)


@tagged('post_install', '-at_install')
class TestSmsIrOtp(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.write({'sms_smsir_enabled': True, 'sms_smsir_api_key': 'KEY', 'sms_smsir_line': '30007732',
                           'sms_smsir_otp_template_id': 100000})

    def test_code_through_the_common_interface(self):
        self.assertTrue(self.company._sms_otp_ready())
        with patch.object(requests.Session, 'request', return_value=answer({'messageId': 99, 'cost': 1.0})) as request:
            self.assertEqual(self.company._sms_otp_send('+989121234567', '123456'), ('smsir', '99'))
        self.assertEqual(request.call_args.args, ('POST', 'https://api.sms.ir/v1/send/verify'))
        self.assertEqual(request.call_args.kwargs['json'], {
            'mobile': '09121234567', 'templateId': 100000, 'parameters': [{'name': 'CODE', 'value': '123456'}]})

    def test_parameter_as_the_template_shows_it(self):
        self.company.sms_smsir_otp_parameter = '#CODE#'
        with patch.object(requests.Session, 'request', return_value=answer({'messageId': 99, 'cost': 1.0})) as request:
            self.company._sms_otp_send('+989121234567', '123456')
        self.assertEqual(request.call_args.kwargs['json']['parameters'], [{'name': 'CODE', 'value': '123456'}])

    def test_not_ready_without_a_template(self):
        self.company.sms_smsir_otp_template_id = 0
        self.assertFalse(self.company._sms_otp_ready())
        with patch.object(requests.Session, 'request') as request, self.assertRaises(SmsIrError):
            self.company._sms_otp_send('+989121234567', '123456')
        request.assert_not_called()

    def test_refused_number(self):
        with patch.object(requests.Session, 'request', return_value=answer(None, 104, "شماره نامعتبر")):
            with self.assertRaises(SmsIrError) as caught:
                self.company._sms_otp_send('+989121234567', '123456')
        self.assertTrue(caught.exception.bad_number)
