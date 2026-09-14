{
    'name': "iKiKu — base",
    'summary': "The spec tree, the Jalali axis, the visibility policy and the verification ledger.",
    'description': """
iKiKu — base
============

Everything generic. The standard/overlay spec tree, provinces and seasons on a
Jalali axis, the three visibility classes that implement بند ۷, and the
assertion/verification ledger that implements بند ۳ and بند ۴.

iKiKu is a cooperative that RECORDS and acts as a union. It is not an employer:
resources are employed by the businesses they are placed with.
    """,
    'author': "شرکت تعاونی ایکیکو",
    'website': "https://ikiku.ir",
    'category': 'Human Resources',
    'version': '19.0.0.1.1',
    'license': 'AGPL-3',
    'depends': ['base', 'mail', 'portal'],
    'data': [
        'security/ikiku_groups.xml',
        'security/ir.model.access.csv',
        'security/ikiku_rules.xml',
        'data/ikiku_province_data.xml',
        'data/ikiku_season_data.xml',
        'data/ikiku_spec_data.xml',
        'data/ikiku_visibility_data.xml',
        'views/ikiku_spec_views.xml',
        'views/ikiku_ledger_views.xml',
        'views/ikiku_geo_views.xml',
        'views/ikiku_menus.xml',
    ],
    'application': True,
    'installable': True,
}
