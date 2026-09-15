{
    'name': "sms.ir SMS",
    'summary': "Send Odoo's SMS through sms.ir directly, without IAP.",
    'description': """
sms.ir SMS
==========

Replaces the transport of Odoo's built-in SMS for a company, as sms_kavenegar
does: the same composer, templates, notifications and trackers, but each message
is posted to sms.ir's REST API instead of Odoo's IAP service. Verification codes
go through an approved sms.ir template, reached through sms_otp.

Differences from Kavenegar that matter to whoever runs it:

* sms.ir documents no delivery callback, so delivery status is polled every ten
  minutes, per send request.
* sms.ir has no client message id and cannot refuse a repeat, so an SMS whose
  request may have reached sms.ir without an answer is marked as unconfirmed,
  never as failed, and says to check the panel before resending.
    """,
    'author': "شرکت تعاونی ایکیکو",
    'website': "https://ikiku.ir",
    'category': 'Hidden/Tools',
    'version': '19.0.1.0.0',
    'license': 'AGPL-3',
    'depends': ['sms', 'sms_otp'],
    'data': [
        'data/ir_cron_data.xml',
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
}
