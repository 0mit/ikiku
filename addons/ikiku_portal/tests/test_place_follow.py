# Part of iKiKu. Licensed under AGPL-3.0.
"""When a café's place changes, the open needs that were at the café follow it; a need placed
elsewhere and a need with a live booking stay, and each is told (operator, 2026-09-22)."""
from odoo.tests import TransactionCase, tagged

from .test_need_changes import place


@tagged('post_install', '-at_install')
class TestPlaceFollow(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.tehran = place(env, "تهران")
        cls.karaj = place(env, "کرج")
        cls.node = env.ref('ikiku_base.spec_dishwashing')
        cls.full = env.ref('ikiku_base.work_type_full_time')
        holder = env['res.partner'].create({'name': "دارنده"})
        cls.business = env['ikiku.business'].create({'name': "کافه نارنج", 'partner_id': holder.id,
                                                     'place_id': cls.tehran.id})
        cls.position = env['ikiku.position'].create({'name': "ظرف‌شور", 'business_id': cls.business.id,
                                                     'spec_node_id': cls.node.id})

    def need(self, place, state='open'):
        return self.env['ikiku.demand'].create({
            'business_id': self.business.id, 'position_id': self.position.id, 'seats': 1,
            'work_type_id': self.full.id, 'place_id': place.id, 'state': state})

    def notes(self, need):
        return [m.body for m in need.message_ids if m.body and 'عوض شد' in m.body]

    def test_a_need_at_the_cafe_follows_it(self):
        need = self.need(self.tehran)
        self.business.write({'place_id': self.karaj.id})
        self.assertEqual(need.place_id, self.karaj)
        self.assertEqual(need.place_city_id, self.karaj)
        self.assertTrue(any("با آن رفت" in n for n in self.notes(need)), self.notes(need))

    def test_a_need_elsewhere_stays_and_is_told(self):
        need = self.need(self.karaj)          # the work is in کرج; the café is in تهران
        self.business.write({'place_id': place(self.env, "مشهد").id})
        self.assertEqual(need.place_id, self.karaj)
        self.assertTrue(any("ماند" in n for n in self.notes(need)), self.notes(need))

    def test_a_closed_need_is_left_alone(self):
        need = self.need(self.tehran, state='filled')
        self.business.write({'place_id': self.karaj.id})
        self.assertEqual(need.place_id, self.tehran)
        self.assertFalse(self.notes(need))

    def test_a_hint_change_alone_follows_without_rebuilding(self):
        need = self.need(self.tehran)
        self.business.write({'place_hint': "کوچهٔ اول"})
        self.assertEqual(need.place_hint, "کوچهٔ اول")
        self.assertEqual(need.place_id, self.tehran)
