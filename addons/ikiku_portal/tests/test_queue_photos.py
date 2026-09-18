# Part of iKiKu. Licensed under AGPL-3.0.
"""Waiting for a workplace that is not hiring, and photos that a person here looks at first
(operator, 2026-09-18)."""
import base64
import io
import re

from odoo.exceptions import UserError
from odoo.tests import HttpCase, TransactionCase, tagged


def place(env, name, kind='city'):
    found = env['place.node'].sudo().search([('kind', '=', kind), ('name', '=', name)], limit=1)
    assert found, "place_ir has no %s called %s" % (kind, name)
    return found


def jpeg_with_gps():
    """A small JPEG carrying an EXIF GPS position, as a phone writes one."""
    from PIL import Image
    image = Image.new('RGB', (64, 48), (200, 120, 40))
    exif = Image.Exif()
    exif[0x8825] = {1: 'N', 2: (35.0, 41.0, 0.0), 3: 'E', 4: (51.0, 25.0, 0.0)}   # GPSInfo
    out = io.BytesIO()
    image.save(out, format='JPEG', exif=exif.tobytes())
    return out.getvalue()


@tagged('post_install', '-at_install')
class TestQueue(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.owner = env['res.partner'].create({'name': "صاحب", 'ikiku_is_verified': True})
        cls.cafe = env['ikiku.business'].create({'name': "کافه صف", 'partner_id': cls.owner.id,
                                                 'place_id': place(env, "تهران").id})
        cls.people = env['res.partner'].create([{'name': "نفر %d" % i} for i in range(3)])
        cls.Favorite = env['ikiku.favorite']

    def test_the_order_of_joining_is_recorded_and_never_reused(self):
        first, second, third = (self.Favorite.ikiku_join(p, self.cafe) for p in self.people)
        self.assertEqual([first.sequence, second.sequence, third.sequence], [1, 2, 3])
        self.assertEqual([first.position, second.position, third.position], [1, 2, 3])
        self.assertEqual(self.Favorite.ikiku_join(self.people[0], self.cafe), first, "joining twice holds one place")
        second.ikiku_leave()
        third.invalidate_recordset()
        self.assertEqual(third.position, 2, "those behind move up")
        again = self.Favorite.ikiku_join(self.people[1], self.cafe)
        self.assertEqual((again.sequence, again.position), (4, 3), "a new number, at the back")

    def test_nobody_queues_for_their_own_workplace(self):
        with self.assertRaises(UserError):
            self.Favorite.ikiku_join(self.owner, self.cafe)


@tagged('post_install', '-at_install')
class TestPhotoIsCleaned(TransactionCase):

    def test_the_location_a_phone_writes_into_a_photo_is_removed(self):
        from PIL import Image
        person = self.env['res.partner'].create({'name': "عکس‌دار"})
        raw = jpeg_with_gps()
        self.assertIn(0x8825, Image.open(io.BytesIO(raw)).getexif(), "the fixture carries a GPS position")
        photo = self.env['ikiku.photo'].ikiku_add(raw, partner=person)
        stored = Image.open(io.BytesIO(base64.b64decode(photo.image)))
        self.assertFalse(stored.getexif(), "no EXIF survives, GPS least of all")
        self.assertEqual((photo.state, photo.is_public), ('pending', False))

    def test_not_a_picture_is_refused_and_a_rejection_needs_a_reason(self):
        person = self.env['res.partner'].create({'name': "عکس‌دار"})
        with self.assertRaises(UserError):
            self.env['ikiku.photo'].ikiku_add(b"%PDF-1.4 not a picture", partner=person)
        photo = self.env['ikiku.photo'].ikiku_add(jpeg_with_gps(), partner=person)
        with self.assertRaises(UserError):
            photo.action_reject()
        photo.reject_reason = "صورتِ کسِ دیگری در عکس است."
        photo.action_reject()
        self.assertEqual(photo.state, 'rejected')


@tagged('post_install', '-at_install')
class TestWorkplacesAndPhotosOnTheSite(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        portal = env.ref('base.group_portal')
        cls.worker = env['res.users'].create({'name': "منتظر", 'login': 'queue-worker', 'password': 'queue-worker-pass-1',
                                              'group_ids': [(6, 0, [portal.id])]})
        env['ikiku.resource'].create({'partner_id': cls.worker.partner_id.id, 'state': 'active'})
        cls.worker.partner_id.place_id = place(env, "تهران")
        cls.holder = env['res.users'].create({'name': "دارنده", 'login': 'queue-holder', 'password': 'queue-holder-pass-1',
                                              'group_ids': [(6, 0, [portal.id])]})
        cls.holder.partner_id.ikiku_is_verified = True
        env.ref('ikiku_base.group_ikiku_business').sudo().user_ids = [(4, cls.holder.id)]
        university = place(env, "دانشگاه تهران", 'neighbourhood')
        cls.quiet = env['ikiku.business'].create({'name': "مجموعهٔ آرام", 'partner_id': cls.holder.partner_id.id,
                                                  'place_id': university.id})
        cls.unverified = env['ikiku.business'].create({'name': "مجموعهٔ ناشناس", 'partner_id': env['res.partner'].create(
            {'name': "دیگری"}).id, 'place_id': university.id})

    def post(self, url, data, page):
        token = re.search(r'name="csrf_token" value="([^"]+)"', self.url_open(page).text).group(1)
        return self.url_open(url, data=dict(data, csrf_token=token), allow_redirects=False)

    def test_a_worker_waits_for_a_verified_workplace_that_is_not_hiring(self):
        self.authenticate('queue-worker', 'queue-worker-pass-1')
        listing = self.url_open('/workplaces').text
        self.assertIn("یک کافه در تهران", listing, "no name until the holder chooses; the city, not the neighbourhood")
        self.assertNotIn("مجموعهٔ آرام", listing)
        self.assertNotIn("مجموعهٔ ناشناس", listing)
        self.assertEqual(listing.count('/queue"'), 1, "only the verified one is listed")
        self.post('/workplaces/%d/queue' % self.quiet.id, {'action': 'join'}, '/workplaces')
        entry = self.env['ikiku.favorite'].sudo().search([('partner_id', '=', self.worker.partner_id.id)])
        self.assertEqual((entry.business_id, entry.sequence), (self.quiet, 1))
        self.assertIn("نفرِ ۱ در صف", self.url_open('/me').text)
        # The holder sees who waits, in order.
        self.authenticate('queue-holder', 'queue-holder-pass-1')
        self.assertIn("منتظر", self.url_open('/business').text)
        self.assertIn("صفِ انتظار: ۱ نفر", self.url_open("/business").text)

    def test_a_photo_is_seen_by_others_only_after_approval(self):
        self.authenticate('queue-worker', 'queue-worker-pass-1')
        token = re.search(r'name="csrf_token" value="([^"]+)"', self.url_open('/me/photos').text).group(1)
        sent = self.url_open('/me/photos', data={'csrf_token': token},
                             files={'photo': ('me.jpg', jpeg_with_gps(), 'image/jpeg')}, allow_redirects=False)
        self.assertEqual(sent.status_code, 303)
        photo = self.env['ikiku.photo'].sudo().search([('partner_id', '=', self.worker.partner_id.id)])
        self.assertEqual(self.url_open('/ikiku/photo/%d' % photo.id).status_code, 200, "its owner sees it")
        self.authenticate(None, None)
        self.assertEqual(self.url_open('/ikiku/photo/%d' % photo.id).status_code, 404, "nobody else, yet")
        photo.action_approve()
        shown = self.url_open('/ikiku/photo/%d' % photo.id)
        self.assertEqual((shown.status_code, shown.headers['Content-Type']), (200, 'image/jpeg'))

    def test_a_job_card_names_the_workplace_only_by_choice(self):
        position = self.env['ikiku.position'].create({'name': "باریستا", 'business_id': self.quiet.id,
                                                      'spec_node_id': self.env.ref('ikiku_base.spec_barista').id})
        self.env['ikiku.demand'].create({'business_id': self.quiet.id, 'position_id': position.id,
                                         'place_id': self.quiet.place_id.id, 'seats': 1, 'state': 'open'})
        self.assertNotIn("مجموعهٔ آرام", self.url_open('/jobs').text)
        self.quiet.name_public = True
        self.assertIn("مجموعهٔ آرام", self.url_open('/jobs').text)
