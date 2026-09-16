# Part of iKiKu. Licensed under AGPL-3.0.
"""Operator decisions of 2026-09-16: work starts today by default, may have no end,
and comes in four kinds; a need with no end goes to anyone free from its start."""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

from odoo.addons.ikiku_base.models.jalali import jalali_date, jalali_month_days


@tagged('post_install', '-at_install')
class TestWorkAndDates(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.today = fields.Date.context_today(env['ikiku.demand'])
        cls.tehran = env.ref('ikiku_base.province_te')
        cls.full = env.ref('ikiku_base.work_type_full_time')
        cls.part = env.ref('ikiku_base.work_type_part_time')
        cls.shift = env.ref('ikiku_base.work_type_per_shift')
        cls.node = env.ref('ikiku_base.spec_dishwashing')
        holder = env['res.partner'].create({'name': "صاحب کافه"})
        cls.business = env['ikiku.business'].create({'name': "کافه آزمایش", 'partner_id': holder.id})
        cls.position = env['ikiku.position'].create({
            'name': "ظرف‌شور", 'business_id': cls.business.id, 'spec_node_id': cls.node.id})

    def worker(self, name, **availability):
        partner = self.env['res.partner'].create({'name': name})
        resource = self.env['ikiku.resource'].create({'partner_id': partner.id, 'state': 'active'})
        vals = {'resource_id': resource.id, 'province_id': self.tehran.id}
        vals.update(availability)
        return resource, self.env['ikiku.availability'].create(vals)

    def need(self, **vals):
        base = {'business_id': self.business.id, 'position_id': self.position.id,
                'province_id': self.tehran.id, 'seats': 1, 'state': 'open'}
        base.update(vals)
        return self.env['ikiku.demand'].create(base)

    def proposed(self, demand):
        return self.env['ikiku.proposal'].build_for_demand(demand).mapped('resource_id')

    def test_defaults_today_and_open_end(self):
        demand = self.need()
        self.assertEqual((demand.date_start, demand.date_end, demand.work_type_id), (self.today, False, self.full))
        self.assertEqual(demand.date_end_fa, "بدون پایان")
        _resource, availability = self.worker("الف")
        self.assertEqual((availability.date_start, availability.date_end_fa), (self.today, "بدون پایان"))
        with self.assertRaises(ValidationError):
            self.need(date_end=self.today - timedelta(days=1))

    def test_an_open_ended_availability_overlaps_what_comes_after(self):
        resource, _availability = self.worker("ب")
        with self.assertRaises(ValidationError):
            self.env['ikiku.availability'].create({
                'resource_id': resource.id, 'province_id': self.tehran.id,
                'date_start': self.today + timedelta(days=100), 'date_end': self.today + timedelta(days=110)})

    def test_a_need_with_an_end_needs_the_whole_window(self):
        whole, _a = self.worker("کامل")
        short, _b = self.worker("کوتاه", date_end=self.today + timedelta(days=10))
        demand = self.need(date_end=self.today + timedelta(days=30))
        found = self.proposed(demand)
        self.assertIn(whole, found)
        self.assertNotIn(short, found)

    def test_a_need_without_an_end_goes_to_anyone_free_from_its_start(self):
        short, availability = self.worker("کوتاه", date_end=self.today + timedelta(days=10))
        later, _b = self.worker("دیرتر", date_start=self.today + timedelta(days=5))
        demand = self.need()
        found = self.proposed(demand)
        self.assertIn(short, found)
        self.assertNotIn(later, found)
        proposal = self.env['ikiku.proposal'].search([('demand_id', '=', demand.id), ('resource_id', '=', short.id)])
        self.assertIn("زمان: آزاد از %s تا %s؛ این نیاز پایان ندارد." % (availability.date_start_fa, availability.date_end_fa),
                      proposal.explanation)

    def test_kind_of_work_filters_but_silence_does_not_exclude(self):
        part_only, _a = self.worker("پاره‌وقت", work_type_ids=[(6, 0, [self.part.id])])
        any_kind, _b = self.worker("نگفته")
        both, _c = self.worker("هر دو", work_type_ids=[(6, 0, [self.full.id, self.shift.id])])
        found = self.proposed(self.need(work_type_id=self.full.id))
        self.assertEqual(set(found.ids) & {part_only.id, any_kind.id, both.id}, {any_kind.id, both.id})
        proposal = self.env['ikiku.proposal'].search([('resource_id', '=', both.id)], limit=1)
        self.assertIn("نوعِ همکاری: تمام‌وقت — می‌پذیرد.", proposal.explanation)
        weights = self.env['ikiku.proposal'].search([('resource_id', '=', any_kind.id)], limit=1)
        self.assertAlmostEqual(weights.score_total, sum([weights.score_competency, weights.score_history,
                                                         weights.score_standing, weights.score_proximity,
                                                         weights.score_season]))

    def test_open_ended_booking_counts_to_the_end_of_the_period(self):
        period = self.env['ikiku.cost.period'].new({
            'date_start': self.today, 'date_end': self.today + timedelta(days=9)})
        booking = self.env['ikiku.booking'].new({'date_start': self.today, 'date_end': False})
        self.assertEqual(period._person_days(booking), 10)

    def test_jalali_dates_are_checked(self):
        self.assertEqual(jalali_month_days(1405, 7), 30)
        self.assertEqual(jalali_date(1405, 7, 1), fields.Date.to_date('2026-09-23'))
        for bad, key in (((1405, 7, 31), 'day'), ((1405, 13, 1), 'month'), ((1200, 1, 1), 'year')):
            with self.assertRaises(ValueError) as caught:
                jalali_date(*bad)
            self.assertEqual(caught.exception.args[0], key)

    def test_signup_tiles_have_everyday_names_in_a_published_order(self):
        Node = self.env['ikiku.spec.node']
        self.assertEqual(self.node.plain_label, "شست‌وشوی ظرف")
        kitchen = Node.search([('kind', '=', 'role'), ('featured', '=', True),
                               ('parent_id', 'child_of', self.env.ref('ikiku_base.spec_kitchen').id)], order='sequence')
        self.assertEqual(kitchen.mapped('code'), ['cook', 'prep', 'dishwashing', 'kebab-cook', 'fast-food-cook', 'chef'])

    def test_open_job_values_follow_the_policy_rows(self):
        self.need(city="تهران", work_type_id=self.part.id, date_end=self.today + timedelta(days=20))
        jobs = self.env['ikiku.demand'].ikiku_public_open()
        mine = [j for j in jobs if j.get('city') == "تهران" and j.get('work_type') == "پاره‌وقت"]
        self.assertTrue(mine)
        self.assertNotIn("کافه آزمایش", str(jobs))
        self.env.ref('ikiku_base.vis_ikiku_demand_city').visibility = 'restricted'
        self.assertFalse(any('city' in j for j in self.env['ikiku.demand'].ikiku_public_open()))
