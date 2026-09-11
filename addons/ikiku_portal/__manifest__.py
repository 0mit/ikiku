{
    'name': "iKiKu — درگاه",
    'summary': "درگاهِ فارسیِ راست‌به‌چپ برای نیرو و کسب‌وکار، و صفحاتِ عمومی.",
    'author': "شرکت تعاونی ایکیکو",
    'website': "https://ikiku.ir",
    'category': 'Website',
    'version': '19.0.0.1.0',
    'license': 'AGPL-3',
    'depends': ['ikiku_match', 'ikiku_coop', 'website', 'portal'],
    'data': [
        'views/ikiku_portal_templates.xml',
        'views/ikiku_public_templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'ikiku_portal/static/src/scss/ikiku.scss',
        ],
    },
    'installable': True,
}
