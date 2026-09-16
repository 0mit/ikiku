# Part of iKiKu. Licensed under AGPL-3.0.
"""How a piece of work is arranged: full-time, part-time, temporary, per shift.

A need has one. A worker's availability lists every kind they accept, and an
availability that lists none has not said, so it is not excluded. The kinds are
data so a page can show the same words and order the matching uses.
"""
from odoo import fields, models


class IkikuWorkType(models.Model):
    _name = 'ikiku.work.type'
    _description = "نوع همکاری"
    _order = 'sequence, id'

    name = fields.Char("نام", required=True)
    code = fields.Char("کد", required=True, help="پایدار؛ کد به آن تکیه می‌کند.")
    description = fields.Char("توضیحِ ساده", help="یک جملهٔ ساده که کنارِ نام روی صفحه می‌آید.")
    sequence = fields.Integer("ترتیب", default=10)
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint('UNIQUE(code)', "کدِ نوعِ همکاری باید یکتا باشد.")
