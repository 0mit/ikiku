{
    'name': "SMS verification codes",
    'summary': "Send a one-time code through whichever SMS provider the company uses.",
    'description': """
SMS verification codes
======================

A seam, not a provider. Code that needs to send a one-time code asks the company
whether it can and sends one, without naming Kavenegar, sms.ir or any other
gateway. Each provider module answers for its own switch and raises a subclass of
SmsOtpError that says whether the number itself was refused.

It also holds the one rule the providers share: a company sends SMS through one
provider at a time, because each of them replaces Odoo's IAP transport and only
one replacement can win.
    """,
    'author': "شرکت تعاونی ایکیکو",
    'website': "https://ikiku.ir",
    'category': 'Hidden/Tools',
    'version': '19.0.1.0.0',
    'license': 'AGPL-3',
    'depends': ['sms'],
    'installable': True,
}
