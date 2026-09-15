# Part of iKiKu. Licensed under AGPL-3.0.
"""The challenge's message id was Kavenegar's by name. With sms.ir beside it the
id is the provider's, and the provider is recorded next to it.

Renamed rather than recreated, so a code sent just before the upgrade keeps its id.
"""
from odoo.tools.sql import column_exists, create_column, rename_column

TABLE = 'ikiku_mobile_challenge'


def migrate(cr, version):
    if not column_exists(cr, TABLE, 'kavenegar_messageid'):
        return
    rename_column(cr, TABLE, 'kavenegar_messageid', 'sms_messageid')
    if not column_exists(cr, TABLE, 'sms_provider'):
        create_column(cr, TABLE, 'sms_provider', 'varchar')
    cr.execute("UPDATE %s SET sms_provider = 'kavenegar' WHERE sms_messageid IS NOT NULL" % TABLE)
