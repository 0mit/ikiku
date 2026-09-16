# Part of iKiKu. Licensed under AGPL-3.0.
"""Help written for people who read slowly: short sentences, spoken Persian (D-9),
plain words for the formal ones (D-10), and nothing promised that is not built.

Every number on these pages is read from the code that enforces it: the SMS limits
from mobile_challenge, the standing rule from ikiku_base, the ranking weights from
ikiku_proposal. «چی رو همه می‌بینن» is built from the visibility policy rows, so the
page cannot promise more privacy, or less, than the code gives.
"""
from odoo import http
from odoo.exceptions import ValidationError
from odoo.http import request

from odoo.addons.ikiku_base.models.jalali import to_fa_digits
from odoo.addons.ikiku_base.models.partner import STANDING_MAX, STANDING_PER_SUPPORTED, STANDING_VERIFIED
from odoo.addons.ikiku_match.models import ikiku_proposal
from odoo.addons.ikiku_portal.controllers.common import day_label, tehran_today
from odoo.addons.ikiku_portal.models import mobile_challenge

PAGES = ('kar', 'niroo', 'code', 'tarikh', 'dide', 'etebar', 'daftar', 'hazine', 'kalame', 'maram',
         'shomare', 'tamas', 'hardo')

# How each classified field is named on the help page. A row with no label here is still
# listed, under its field's own label, so a new row can never silently disappear.
PLAIN_FIELDS = {
    ('res.partner', 'name'): "اسمتون",
    ('res.partner', 'function'): "عنوانِ کاری‌تون",
    ('res.partner', 'ikiku_province_id'): "استان",
    ('res.partner', 'ikiku_city'): "شهر",
    ('res.partner', 'ikiku_standing'): "اعتبار، همیشه با راهِ رسیدن به عددش",
    ('res.partner', 'ikiku_is_verified'): "اینکه هویتتون تأیید شده یا نه",
    ('res.partner', 'ikiku_mobile'): "شماره موبایل",
    ('res.partner', 'ikiku_mobile_verified_on'): None,
    ('res.partner', 'phone'): None,   # the same number as ikiku_mobile since 2026-09-16
    ('res.partner', 'ikiku_mobile_set_by_id'): None,
    ('res.partner', 'ikiku_mobile_state'): None,
    ('res.partner', 'mobile'): None,
    ('res.partner', 'email'): "ایمیل",
    ('res.partner', 'street'): "آدرسِ خونه",
    ('res.partner', 'street2'): None,
    ('res.partner', 'zip'): "کدپستی",
    ('res.partner', 'ikiku_nid_hash'): "کدِ ملی",
    ('res.partner', 'ikiku_nid_checked_on'): None,
    ('ikiku.demand', 'seats'): "چند نفر لازمه",
    ('ikiku.demand', 'work_type_id'): "نوعِ همکاری",
    ('ikiku.demand', 'province_id'): "استان",
    ('ikiku.demand', 'city'): "شهر",
    ('ikiku.demand', 'date_start'): "از کِی",
    ('ikiku.demand', 'date_end'): "تا کِی",
    ('ikiku.demand', 'business_id'): "اسمِ کافه یا رستوران",
    ('ikiku.demand', 'position_id'): "اسمی که خودِ کافه یا رستوران روی اون کار گذاشته",
    ('ikiku.demand', 'note'): "یادداشتِ کافه یا رستوران",
    ('ikiku.demand', 'cancel_reason'): "دلیلی که برای لغو نوشتید",
    ('ikiku.demand', 'closed_on'): None,
    ('ikiku.demand', 'closed_by_id'): None,
    ('ikiku.business', 'partner_id'): "اینکه کافه یا رستوران مالِ کیه",
    ('ikiku.business', 'province_id'): "استان و شهرِ کافه یا رستوران",
    ('ikiku.business', 'city'): None,
}

# The booking states as a person says them (D-10: قرار کار).
BOOKING_STATES = {
    'confirmed': "قطعی",
    'at_risk': "دوباره بررسی میشه",
    'replaced': "نفر عوض شد",
    'in_progress': "سرِ کار",
    'done': "تموم شد",
    'cancelled': "به هم خورد",
}


def _num(value):
    """0.25 -> ۰٫۲۵, 5.0 -> ۵"""
    return to_fa_digits(('%g' % value).replace('.', '٫'))


class IkikuHelp(http.Controller):

    def _rows(self, model_name):
        Policy = request.env['ikiku.visibility.policy'].sudo()
        out = {'public': [], 'counterparty': [], 'restricted': []}
        for row in Policy.search([('model_name', '=', model_name)]):
            key = (model_name, row.field_name)
            if key in PLAIN_FIELDS:
                label = PLAIN_FIELDS[key]
            else:
                field = request.env[model_name]._fields.get(row.field_name)
                label = field.string if field else row.field_name
            if label and label not in out[row.visibility]:
                out[row.visibility].append(label)
        return out

    def _values(self, page):
        values = {'page': page}
        if page == 'code':
            values.update({
                'resend_minutes': to_fa_digits(int(mobile_challenge.RESEND_AFTER.total_seconds() // 60)),
                'per_hour': to_fa_digits(mobile_challenge.MAX_SENDS_PER_HOUR),
                'code_ttl': mobile_challenge.duration_text(mobile_challenge.CODE_TTL),
                'code_digits': to_fa_digits(mobile_challenge.CODE_DIGITS),
            })
        elif page == 'etebar':
            values.update({
                'verified': _num(STANDING_VERIFIED), 'per_supported': _num(STANDING_PER_SUPPORTED),
                'max': _num(STANDING_MAX),
                'example_two': _num(2 * STANDING_PER_SUPPORTED),
                'example_total': _num(min(STANDING_VERIFIED + 2 * STANDING_PER_SUPPORTED, STANDING_MAX)),
                'weights': [
                    ("کار (مهارت‌هایی که تأیید شده)", _num(ikiku_proposal.W_COMPETENCY)),
                    ("سابقه‌ی تأییدشده", _num(ikiku_proposal.W_HISTORY)),
                    ("اعتبار", _num(ikiku_proposal.W_STANDING)),
                    ("نزدیکی", _num(ikiku_proposal.W_PROXIMITY)),
                    ("فصل", _num(ikiku_proposal.W_SEASON)),
                ],
            })
        elif page == 'dide':
            values.update({
                'person': self._rows('res.partner'),
                'job': self._rows('ikiku.demand'),
                'availability': self._rows('ikiku.availability'),
                'cafe': self._rows('ikiku.business'),
            })
        elif page == 'daftar':
            values['states'] = list(BOOKING_STATES.values())
        elif page == 'tarikh':
            values['today'] = day_label(tehran_today())
        elif page == 'maram':
            values['version'] = to_fa_digits('0.3')
        return values

    @http.route('/help', type='http', auth='public', website=True)
    def hub(self, **kw):
        return request.render('ikiku_portal.help_hub', {'page': 'hub'})

    @http.route('/help/<string:page>', type='http', auth='public', website=True, methods=['GET'])
    def page(self, page, **kw):
        if page not in PAGES:
            return request.not_found()
        values = self._values(page)
        if page == 'tamas':
            values.update({'sent': kw.get('sent') == '1', 'form': {'from_page': kw.get('from', '')[:60]},
                           'errors': {}})
        return request.render('ikiku_portal.help_%s' % page, values)

    @http.route('/help/tamas', type='http', auth='public', website=True, methods=['POST'], csrf=True)
    def call_back(self, **post):
        form = {key: ' '.join((post.get(key) or '').split())[:200]
                for key in ('name', 'mobile', 'best_time', 'topic', 'from_page')}
        errors = {}
        if post.get('website_url'):
            # A field people never see; only a script fills it.
            return request.redirect('/help/tamas?sent=1')
        if not form['name']:
            errors['name'] = "اسمتون رو بنویسید."
        try:
            mobile = request.env['res.partner'].sudo().normalise_mobile(form['mobile'])
        except ValidationError:
            mobile = False
        if not mobile:
            errors['mobile'] = mobile_challenge.MESSAGES['mobile']
        if form['best_time'] not in ('morning', 'noon', 'evening'):
            errors['best_time'] = "بگید کِی زنگ بزنیم."
        Request = request.env['ikiku.help.request'].sudo()
        if not errors and Request.too_many(mobile):
            errors['mobile'] = "امروز برای این شماره درخواست گذاشتید. تیمِ ایکیکو زنگ می‌زنه."
        if errors:
            values = self._values('tamas')
            values.update({'sent': False, 'form': form, 'errors': errors})
            return request.render('ikiku_portal.help_tamas', values)
        user = request.env.user
        Request.create({
            'name': form['name'], 'mobile': mobile, 'best_time': form['best_time'],
            'topic': form['topic'], 'from_page': form['from_page'],
            'partner_id': False if user._is_public() else user.partner_id.id,
        })
        return request.redirect('/help/tamas?sent=1')
