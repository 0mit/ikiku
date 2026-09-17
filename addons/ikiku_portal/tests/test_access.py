# Part of iKiKu. Licensed under AGPL-3.0.
"""What a portal account may read and write by itself (the design review of 2026-09-16).

Every portal page writes through sudo controllers that check ownership. Until then a
fresh SMS account could write every need, business and availability over RPC, and a
worker could rewrite a proposal's score (بند ۸) or a booking's state (بند ۷)."""
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


def place(env, name, kind='city'):
    """A place from place_ir, by name. Tests say «تهران» and «کرج», not an xmlid nobody reads."""
    found = env['place.node'].sudo().search([('kind', '=', kind), ('name', '=', name)], limit=1)
    assert found, "place_ir has no %s called %s" % (kind, name)
    return found


@tagged('post_install', '-at_install')
class TestPortalAccess(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.tehran = place(env, "تهران")
        cls.karaj = place(env, "کرج")
        cls.node = env.ref('ikiku_base.spec_dishwashing')
        portal = env.ref('base.group_portal')
        worker_group = env.ref('ikiku_base.group_ikiku_resource')
        business_group = env.ref('ikiku_base.group_ikiku_business')

        def user(login, groups):
            return env['res.users'].with_context(no_reset_password=True).create({
                'name': login, 'login': login, 'group_ids': [(6, 0, [g.id for g in groups])]})

        cls.plain = user('acc-plain', [portal])
        cls.worker = user('acc-worker', [worker_group])
        cls.owner = user('acc-owner', [business_group])
        cls.dual = user('acc-dual', [worker_group, business_group])

        def business(partner, name):
            return env['ikiku.business'].create({'name': name, 'partner_id': partner.id})

        cls.other_business = business(env['res.partner'].create({'name': "دیگری"}), "کافه دیگر")
        cls.own_business = business(cls.dual.partner_id, "کافه خودم")
        business(cls.owner.partner_id, "کافه مالک")

        def need(biz):
            position = env['ikiku.position'].create({'name': "ظرف‌شور", 'business_id': biz.id,
                                                     'spec_node_id': cls.node.id})
            return env['ikiku.demand'].create({'business_id': biz.id, 'position_id': position.id,
                                               'place_id': cls.tehran.id, 'seats': 1, 'state': 'open'})

        cls.other_need = need(cls.other_business)
        cls.own_need = need(cls.own_business)

        def worker(partner):
            resource = env['ikiku.resource'].create({'partner_id': partner.id, 'state': 'active'})
            availability = env['ikiku.availability'].create({'resource_id': resource.id,
                                                             'place_id': cls.tehran.id})
            return resource, availability

        cls.dual_resource, cls.dual_availability = worker(cls.dual.partner_id)
        cls.worker_resource, cls.worker_availability = worker(cls.worker.partner_id)
        cls.stranger_resource, _ = worker(env['res.partner'].create({'name': "غریبه"}))
        cls.dual_proposal = env['ikiku.proposal'].create({'demand_id': cls.other_need.id,
                                                          'resource_id': cls.dual_resource.id})
        cls.dual_booking = env['ikiku.booking'].create({'demand_id': cls.other_need.id,
                                                        'resource_id': cls.dual_resource.id})

    def test_plain_portal_reads_no_ikiku_rows(self):
        for model in ('ikiku.demand', 'ikiku.business', 'ikiku.position', 'ikiku.resource',
                      'ikiku.availability', 'ikiku.proposal', 'ikiku.booking', 'ikiku.booking.check'):
            with self.subTest(model=model), self.assertRaises(AccessError):
                self.env[model].with_user(self.plain).search([])

    def test_worker_cannot_touch_needs(self):
        Demand = self.env['ikiku.demand'].with_user(self.worker)
        with self.assertRaises(AccessError):
            Demand.search([])
        with self.assertRaises(AccessError):
            self.other_need.with_user(self.worker).write({'seats': 9})

    def test_business_never_reads_availability(self):
        availability = self.worker_availability.with_user(self.owner)
        with self.assertRaises(AccessError):
            availability.read(['date_start'])
        with self.assertRaises(AccessError):
            self.env['ikiku.availability'].with_user(self.owner).search([])
        with self.assertRaises(AccessError):
            availability.write({'place_id': self.karaj.id})
        with self.assertRaises(AccessError):
            availability.unlink()
        with self.assertRaises(AccessError):
            self.worker_resource.with_user(self.owner).read(['name'])

    def test_dual_reads_its_own_and_writes_nothing(self):
        dual = self.dual
        self.assertEqual(self.env['ikiku.demand'].with_user(dual).search([]), self.own_need)
        self.assertIn(self.dual_availability, self.env['ikiku.availability'].with_user(dual).search([]))
        self.assertEqual(self.env['ikiku.proposal'].with_user(dual).search([]), self.dual_proposal)
        with self.assertRaises(AccessError):
            self.dual_proposal.with_user(dual).write({'score_total': 99})
        with self.assertRaises(AccessError):
            self.dual_booking.with_user(dual).write({'state': 'cancelled'})
        with self.assertRaises(AccessError):
            self.own_need.with_user(dual).write({'seats': 9})
        with self.assertRaises(AccessError):
            self.other_need.with_user(dual).read(['seats'])

    def test_the_ledger_is_read_only_for_portal(self):
        assertion = self.env['ikiku.assertion'].create({
            'resource_id': self.worker.partner_id.id, 'asserted_by_id': self.worker.partner_id.id,
            'claim_kind': 'skill', 'spec_node_id': self.node.id})
        with self.assertRaises(AccessError):
            self.env['ikiku.assertion'].with_user(self.worker).create({
                'resource_id': self.worker.partner_id.id, 'asserted_by_id': self.worker.partner_id.id,
                'claim_kind': 'skill', 'spec_node_id': self.node.id})
        with self.assertRaises(AccessError):
            self.env['ikiku.verification'].with_user(self.owner).create({
                'assertion_id': assertion.id, 'verifier_id': self.owner.partner_id.id})

    def test_skills_are_their_own(self):
        skill = self.env['ikiku.resource.skill'].search([('resource_id', '=', self.stranger_resource.id)], limit=1)
        visible = self.env['ikiku.resource.skill'].with_user(self.worker).search([])
        self.assertFalse(visible.filtered(lambda s: s.resource_id != self.worker_resource))
        if skill:
            with self.assertRaises(AccessError):
                skill.with_user(self.worker).read(['resource_id'])
