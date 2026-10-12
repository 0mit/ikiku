# Part of iKiKu. Licensed under AGPL-3.0.
"""Staff find a café by its name as people type it, and nobody finds one they may not read.

A business's name is private until its holder makes it public (name_public); the index holds
it either way, because the staff look a café up by the name on its door. The index is read
where the name is, by the same few: the staff, the register's reader, the holder of that café
-- and no public page, where a field with no visibility row is restricted."""
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestBusinessSuggest(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.holder = env['res.users'].with_context(no_reset_password=True).create({
            'name': "دارندهٔ نارنج", 'login': 'suggest-holder',
            'group_ids': [(6, 0, [env.ref('ikiku_base.group_ikiku_business').id])]})
        other = env['res.partner'].create({'name': "دارندهٔ دیگر"})
        Business = env['ikiku.business']
        cls.narenj = Business.create({'name': "کافهٔ نارنج", 'partner_id': cls.holder.partner_id.id})
        cls.gilaneh = Business.create({'name': "رستوران گیلانه", 'partner_id': other.id, 'name_public': True})
        cls.sangak = Business.create({'name': "نانوایی سنگکِ نارنج", 'partner_id': other.id})
        cls.mine = [('id', 'in', (cls.narenj | cls.gilaneh | cls.sangak).ids)]

    def found(self, query, Business=None):
        Business = Business if Business is not None else self.env['ikiku.business']
        return [result['record'] for result in Business.suggest(query, domain=self.mine)]

    def test_found_as_people_type_it(self):
        self.assertEqual(self.found("كافه نارنج")[0], self.narenj, "an Arabic kaf, no hamza")
        self.assertEqual(self.found("گيلانه")[0], self.gilaneh, "an Arabic yeh")
        self.assertEqual(set(self.found("نارنج")), {self.narenj, self.sangak}, "a word of the name, anywhere in it")
        self.assertIn('کافه نارنج', self.narenj.suggest_index)

    def test_the_index_follows_the_name(self):
        self.narenj.name = "کافهٔ ترنج"
        self.assertEqual(self.found("ترنج"), [self.narenj])
        self.assertEqual(self.found("نارنج"), [self.sangak], "the old name's word no longer finds it")

    def test_nobody_finds_a_cafe_they_may_not_read(self):
        as_holder = self.env['ikiku.business'].with_user(self.holder)
        self.assertEqual(self.found("نارنج", as_holder), [self.narenj], "the holder finds their own and only it")
        self.assertEqual(self.found("گیلانه", as_holder), [])
        plain = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': "کسی", 'login': 'suggest-plain', 'group_ids': [(6, 0, [self.env.ref('base.group_portal').id])]})
        with self.assertRaises(AccessError):
            self.env['ikiku.business'].with_user(plain).suggest("نارنج")
        self.assertNotIn('suggest_index', self.narenj.ikiku_public_values('public'))
        self.assertNotIn('suggest_index', self.narenj.ikiku_public_values('counterparty'))
