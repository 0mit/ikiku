# Part of iKiKu. Licensed under AGPL-3.0.
import json
from datetime import timedelta
from unittest.mock import patch

import requests

from odoo import fields
from odoo.tests import HttpCase, TransactionCase, tagged

from odoo.addons.sms.tools.sms_api import SmsApi
from odoo.addons.sms_kavenegar.tools.kavenegar import KavenegarClient, KavenegarError
from odoo.addons.sms_kavenegar.tools.sms_api import local_id


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload, self.status_code = payload, status_code

    def json(self):
        return self.payload


def answer(entries, status=200, message="تایید شد"):
    return FakeResponse({'return': {'status': status, 'message': message}, 'entries': entries},
                        200 if status == 200 else status)


def sendarray_echo(status=1):
    """Answer a sendarray the way Kavenegar does: one entry per receptor, in order."""
    counter = iter(range(9000000, 10000000))

    def post(url, data=None, timeout=None):
        receptors = json.loads(data['receptor'])
        return answer([{'messageid': next(counter), 'status': status, 'statustext': 'x',
                        'receptor': r, 'sender': '10004346', 'cost': 120} for r in receptors])
    return post


@tagged('post_install', '-at_install')
class TestKavenegarClient(TransactionCase):

    def test_url_arrays_and_timeout(self):
        with patch.object(requests.Session, 'post', return_value=answer([])) as post:
            KavenegarClient('KEY123').send_array(['+989121234567'], ['10004346'], ['سلامِ آزمایشی'], [7])
        url = post.call_args.args[0]
        data, timeout = post.call_args.kwargs['data'], post.call_args.kwargs['timeout']
        self.assertEqual(url, 'https://api.kavenegar.com/v1/KEY123/sms/sendarray.json')
        self.assertEqual(json.loads(data['receptor']), ['+989121234567'])
        self.assertEqual(json.loads(data['message']), ['سلامِ آزمایشی'])
        self.assertEqual(json.loads(data['localmessageids']), [7])
        self.assertEqual(timeout, 30)

    def test_errors_never_carry_the_key(self):
        leak = requests.exceptions.ConnectionError(
            "HTTPSConnectionPool(host='api.kavenegar.com'): Max retries exceeded with url: /v1/SECRETKEY/account/info.json")
        with patch.object(requests.Session, 'post', side_effect=leak):
            with self.assertRaises(KavenegarError) as caught:
                KavenegarClient('SECRETKEY').account_info()
        self.assertEqual(caught.exception.status, 0)
        self.assertNotIn('SECRETKEY', str(caught.exception))

    def test_refusal_is_an_error(self):
        with patch.object(requests.Session, 'post', return_value=answer(None, 403, "کد شناسائی معتبر نمی باشد")):
            with self.assertRaises(KavenegarError) as caught:
                KavenegarClient('BAD').account_info()
        self.assertEqual(caught.exception.status, 403)


@tagged('post_install', '-at_install')
class TestKavenegarSending(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.write({'sms_kavenegar_enabled': True, 'sms_kavenegar_api_key': 'KEY',
                           'sms_kavenegar_sender': '10004346'})

    def make_sms(self, count=1, body="کدِ آزمایشی"):
        return self.env['sms.sms'].create([
            {'number': '+98912%07d' % i, 'body': body} for i in range(count)])

    def test_kavenegar_is_used_and_iap_is_not(self):
        sms = self.make_sms()
        with patch.object(SmsApi, '_contact_iap', side_effect=AssertionError("IAP was contacted")), \
                patch.object(requests.Session, 'post', side_effect=sendarray_echo()) as post:
            sms.send(unlink_sent=False)
        self.assertEqual(post.call_count, 1)
        self.assertIn('/KEY/sms/sendarray.json', post.call_args.args[0])
        self.assertEqual(json.loads(post.call_args.kwargs['data']['localmessageids']), [local_id(sms.uuid)])
        self.assertEqual(sms.state, 'pending')

    def test_batches_of_two_hundred(self):
        sms = self.make_sms(250)
        with patch.object(requests.Session, 'post', side_effect=sendarray_echo()) as post:
            sms.send(unlink_sent=False)
        self.assertEqual([len(json.loads(c.kwargs['data']['receptor'])) for c in post.call_args_list], [200, 50])
        self.assertEqual(set(sms.mapped('state')), {'pending'})

    def test_no_credit(self):
        sms = self.make_sms(2)
        with patch.object(requests.Session, 'post', return_value=answer(None, 418, "اعتبار کافی نیست")):
            sms.send(unlink_failed=False, unlink_sent=False)
        self.assertEqual(set(sms.mapped('state')), {'error'})
        self.assertEqual(set(sms.mapped('failure_type')), {'sms_credit'})

    def test_unreachable(self):
        sms = self.make_sms()
        with patch.object(requests.Session, 'post', side_effect=requests.exceptions.Timeout()):
            sms.send(unlink_failed=False, unlink_sent=False)
        self.assertEqual((sms.state, sms.failure_type), ('error', 'sms_server'))

    def test_bad_key(self):
        sms = self.make_sms()
        with patch.object(requests.Session, 'post', return_value=answer(None, 403, "کد شناسائی معتبر نمی باشد")):
            sms.send(unlink_failed=False, unlink_sent=False)
        self.assertEqual((sms.state, sms.failure_type), ('error', 'kavenegar_account'))

    def test_blocked_receptor(self):
        sms = self.make_sms()
        with patch.object(requests.Session, 'post', side_effect=sendarray_echo(status=14)):
            sms.send(unlink_failed=False, unlink_sent=False)
        self.assertEqual(sms.state, 'error')

    def test_missing_sender(self):
        self.company.sms_kavenegar_sender = False
        sms = self.make_sms()
        with patch.object(requests.Session, 'post') as post:
            sms.send(unlink_failed=False, unlink_sent=False)
        post.assert_not_called()
        self.assertEqual((sms.state, sms.failure_type), ('error', 'kavenegar_sender'))

    def test_disabled_company_keeps_iap(self):
        self.company.sms_kavenegar_enabled = False
        sms = self.make_sms()
        with patch.object(SmsApi, '_send_sms_batch', return_value=[{'uuid': sms.uuid, 'state': 'success'}]) as iap, \
                patch.object(requests.Session, 'post', side_effect=AssertionError("Kavenegar was contacted")):
            sms.send(unlink_sent=False)
        iap.assert_called_once()


@tagged('post_install', '-at_install')
class TestKavenegarDelivery(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.write({'sms_kavenegar_enabled': True, 'sms_kavenegar_api_key': 'KEY',
                           'sms_kavenegar_sender': '10004346'})
        partner = cls.env['res.partner'].create({'name': "گیرنده"})
        message = partner.message_post(body="x", message_type='sms')
        cls.notification = cls.env['mail.notification'].create({
            'mail_message_id': message.id, 'res_partner_id': partner.id,
            'notification_type': 'sms', 'notification_status': 'pending'})
        cls.tracker = cls.env['sms.tracker'].create({
            'sms_uuid': 'a' * 32, 'mail_notification_id': cls.notification.id,
            'kavenegar_messageid': '8792343', 'kavenegar_status': 1,
            'kavenegar_company_id': cls.company.id, 'kavenegar_sent_at': fields.Datetime.now()})

    def test_statuses(self):
        self.tracker._kavenegar_apply_status(10)
        self.assertEqual(self.notification.notification_status, 'sent')
        other = self.env['res.partner'].create({'name': "گیرندهٔ دوم"})
        notification = self.notification.copy({'res_partner_id': other.id, 'notification_status': 'pending'})
        tracker = self.tracker.copy({'sms_uuid': 'b' * 32, 'mail_notification_id': notification.id})
        tracker._kavenegar_apply_status(11)
        self.assertEqual((notification.notification_status, notification.failure_type),
                         ('exception', 'sms_not_delivered'))

    def test_polling(self):
        stale = self.tracker.copy({'sms_uuid': 'c' * 32, 'kavenegar_messageid': '1',
                                   'kavenegar_sent_at': fields.Datetime.now() - timedelta(hours=49)})
        with patch.object(requests.Session, 'post', return_value=answer([{'messageid': 8792343, 'status': 10}])) as post:
            self.env['sms.tracker']._kavenegar_poll_status()
        self.assertEqual(post.call_args.kwargs['data']['messageid'], '8792343')
        self.assertEqual(self.tracker.kavenegar_status, 10)
        self.assertEqual(stale.kavenegar_status, 1)

    def test_callback_needs_the_token(self):
        token = self.company.sudo().sms_kavenegar_callback_token
        wrong = self.url_open('/sms_kavenegar/status/%s' % ('0' * 32), data={'messageid': '8792343', 'status': '10'})
        self.assertEqual(wrong.status_code, 404)
        self.assertEqual(self.tracker.kavenegar_status, 1)
        right = self.url_open('/sms_kavenegar/status/%s' % token, data={'messageid': '8792343', 'status': '10'})
        self.assertEqual((right.status_code, right.text), (200, 'OK'))
        self.assertEqual(self.tracker.kavenegar_status, 10)
        unknown = self.url_open('/sms_kavenegar/status/%s' % token, data={'messageid': '5', 'status': '10'})
        self.assertEqual(unknown.status_code, 200)
