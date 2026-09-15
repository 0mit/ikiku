{
    'name': "Kavenegar SMS",
    'summary': "Send Odoo's SMS through Kavenegar (کاوه‌نگار) directly, without IAP.",
    'description': """
Kavenegar SMS
=============

Replaces the transport of Odoo's built-in SMS for a company: the same composer,
templates, notifications and trackers, but each message is posted to
Kavenegar's REST API instead of Odoo's IAP service. Delivery status comes back
through a token-protected callback and a polling job as a safety net.

Built after sms_twilio, Odoo's own example of a provider that bypasses IAP.
The iap and iap_mail modules are still installed as dependencies of sms; with
Kavenegar enabled they are never contacted to send.
    """,
    'author': "شرکت تعاونی ایکیکو",
    'website': "https://ikiku.ir",
    'category': 'Hidden/Tools',
    'version': '19.0.1.1.0',
    'license': 'AGPL-3',
    'depends': ['sms', 'sms_otp'],
    'data': [
        'data/ir_cron_data.xml',
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
}
