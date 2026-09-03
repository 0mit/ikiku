{
    'name': "iKiKu — گمارش",
    'summary': "پیشنهاد، رتبه‌بندیِ خوانا، گمارشِ عمومی، و بازبینیِ پیش از شروع.",
    'author': "شرکت تعاونی ایکیکو",
    'website': "https://ikiku.ir",
    'category': 'Human Resources',
    'version': '19.0.0.1.0',
    'license': 'AGPL-3',
    'depends': ['ikiku_supply', 'ikiku_demand', 'project'],
    'data': [
        'security/ir.model.access.csv',
        'security/ikiku_match_rules.xml',
        'data/ikiku_match_data.xml',
        'data/ikiku_cron.xml',
        'views/ikiku_match_views.xml',
        'views/ikiku_match_menus.xml',
    ],
    'installable': True,
}
