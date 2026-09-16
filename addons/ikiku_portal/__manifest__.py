{
    'name': "iKiKu — درگاه",
    'summary': "درگاهِ فارسیِ راست‌به‌چپ برای نیرو و کسب‌وکار، و صفحاتِ عمومی.",
    'author': "شرکت تعاونی ایکیکو",
    'website': "https://ikiku.ir",
    'category': 'Website',
    'version': '19.0.0.1.2',
    'license': 'AGPL-3',
    'depends': ['ikiku_match', 'ikiku_coop', 'website', 'portal', 'auth_signup',
                'sms_otp', 'sms_kavenegar', 'sms_smsir'],
    'data': [
        'security/ir.model.access.csv',
        'data/ikiku_otp_data.xml',
        'views/ikiku_enter_templates.xml',
        'views/ikiku_portal_templates.xml',
        'views/ikiku_staff_views.xml',
        'views/ikiku_public_templates.xml',
        'views/ikiku_site_templates.xml',
        'views/ikiku_site_chrome.xml',
        'data/ikiku_site_data.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'ikiku_portal/static/src/scss/ikiku.scss',
            'ikiku_portal/static/src/js/ikiku_otp.js',
        ],
    },
    'installable': True,
}
