# Part of iKiKu. Licensed under AGPL-3.0.
"""Staff find a worker by their name as people type it; the index follows the person's own name."""
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestResourceSuggest(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.worker = env['res.users'].with_context(no_reset_password=True).create({
            'name': "آزمون رضایی", 'login': 'suggest-worker',
            'group_ids': [(6, 0, [env.ref('ikiku_base.group_ikiku_resource').id])]})
        Resource = env['ikiku.resource']
        cls.rezaei = Resource.create({'partner_id': cls.worker.partner_id.id})
        cls.maryam = Resource.create({'partner_id': env['res.partner'].create({'name': "مریم آزمون‌زاده"}).id})
        cls.mine = [('id', 'in', (cls.rezaei | cls.maryam).ids)]

    def found(self, query, Resource=None):
        Resource = Resource if Resource is not None else self.env['ikiku.resource']
        return [result['record'] for result in Resource.suggest(query, domain=self.mine)]

    def test_found_as_people_type_it(self):
        self.assertEqual(self.found("رضايي")[0], self.rezaei, "an Arabic yeh")
        self.assertEqual(self.found("ازمون زاده")[0], self.maryam, "no madda, a space for the ZWNJ")
        self.assertEqual(self.found("ازمونزاده")[0], self.maryam, "no space at all")

    def test_the_index_follows_the_persons_name(self):
        self.maryam.partner_id.name = "مریم نارنجی"
        self.assertEqual(self.found("نارنجی"), [self.maryam])
        self.assertNotIn(self.maryam, self.found("آزمون‌زاده"))

    def test_a_worker_finds_only_themselves(self):
        as_worker = self.env['ikiku.resource'].with_user(self.worker)
        self.assertEqual(self.found("آزمون", as_worker), [self.rezaei])
        owner = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': "کافه‌دار", 'login': 'suggest-owner',
            'group_ids': [(6, 0, [self.env.ref('ikiku_base.group_ikiku_business').id])]})
        with self.assertRaises(AccessError):
            self.env['ikiku.resource'].with_user(owner).suggest("آزمون")
