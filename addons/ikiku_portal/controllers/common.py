# Part of iKiKu. Licensed under AGPL-3.0.
"""What every portal form shares: numbers in any digits, and dates as buttons.

Dates are chosen, never typed (the design review of 2026-09-16). The buttons print
absolute Jalali dates computed for today in Tehran; custom dates come from three
selects and go through jalali_date, which refuses 31 Mehr instead of rolling it
over. A start defaults to today and an end may be «بدون پایان» (operator decisions).
"""
from datetime import timedelta

from odoo import fields
from odoo.http import request

from odoo.addons.ikiku_base.models.jalali import (
    JALALI_MONTHS_FA, gregorian_to_jalali, jalali_date, jalali_month_days, jalali_to_gregorian,
    to_fa_digits, to_latin_digits)

TEHRAN = 'Asia/Tehran'


def mask(mobile):
    """+989121234567 -> ۰۹۱۲•••۴۵۶۷: enough for a person to know their own number, and
    never the whole number in a page."""
    if not mobile or len(mobile) < 10:
        return ''
    local = '0' + mobile[-10:]
    return to_fa_digits(local[:4]) + '•••' + to_fa_digits(local[-4:])

DATE_ERRORS = {
    'start_missing': "روزِ شروع رو انتخاب کنید.",
    'start_bad': "این تاریخ درست نیست. روز و ماه رو دوباره انتخاب کنید.",
    'start_day': "این ماه این‌قدر روز نداره. روز رو دوباره انتخاب کنید.",
    'start_past': "این روز گذشته. امروز یا یه روزِ بعد رو انتخاب کنید.",
    'end_missing': "بگید تا کِی. اگه معلوم نیست، «بدون پایان» رو بزنید.",
    'end_bad': "این تاریخ درست نیست. روز و ماه رو دوباره انتخاب کنید.",
    'end_day': "این ماه این‌قدر روز نداره. روز رو دوباره انتخاب کنید.",
    'order': "روزِ آخر باید بعد از روزِ اول باشه.",
    'overlap': "این تاریخ‌ها با تاریخ‌هایی که قبلاً دادید یکی شده. همون قبلی رو عوض کنید.",
}


def to_int(value, default=None):
    """A number from a form, in whatever digits it was typed; `default` when it is not one,
    rather than a server error."""
    try:
        return int(to_latin_digits(value).strip())
    except (AttributeError, TypeError, ValueError):
        return default


def parse_jalali(value):
    """A typed Jalali date such as ۱۴۰۵/۰۹/۰۱ -> ISO Gregorian string, or False."""
    if not value:
        return False
    parts = to_latin_digits(value).strip().replace('-', '/').replace('.', '/').split('/')
    if len(parts) != 3:
        return False
    try:
        return jalali_date(*(int(p) for p in parts)).isoformat()
    except ValueError:
        return False


def tehran_today():
    return fields.Date.context_today(request.env['res.users'].with_context(tz=TEHRAN))


def _jalali(day):
    return gregorian_to_jalali(day.year, day.month, day.day)


def day_label(day, today=None):
    """۲۵ شهریور, with the year only when it is not this year."""
    if not day:
        return ""
    jy, jm, jd = _jalali(day)
    text = "%d %s" % (jd, JALALI_MONTHS_FA[jm - 1])
    if today is None or _jalali(today)[0] != jy:
        text += " %d" % jy
    return to_fa_digits(text)


def add_months(day, months):
    jy, jm, jd = _jalali(day)
    index = jm - 1 + months
    jy, jm = jy + index // 12, index % 12 + 1
    return jalali_date(jy, jm, min(jd, jalali_month_days(jy, jm)))


def first_of_next_month(day):
    jy, jm, _jd = _jalali(day)
    return jalali_date(jy + 1, 1, 1) if jm == 12 else jalali_date(jy, jm + 1, 1)


def end_of_year(day):
    jy = _jalali(day)[0]
    return jalali_date(jy, 12, jalali_month_days(jy, 12))


def next_saturday(day):
    return day + timedelta(days=(5 - day.weekday()) % 7 or 7)


def date_widget(kind, values=None):
    """Values for ikiku_portal.date_choices. `kind` is 'worker' or 'business'."""
    today = tehran_today()
    values = values or {}
    jy = _jalali(today)[0]
    starts = [('today', "از امروز (%s)" % day_label(today, today))]
    if kind == 'business':
        starts.append(('week', "از هفته‌ی بعد (شنبه %s)" % day_label(next_saturday(today), today)))
    starts.append(('month', "از اولِ ماهِ بعد (%s)" % day_label(first_of_next_month(today), today)))
    if kind == 'business':
        ends = [('1d', "۱ روز"), ('1w', "۱ هفته"), ('1m', "۱ ماه"), ('3m', "۳ ماه"),
                ('none', "بدون پایان")]
    else:
        ends = [('none', "بدون پایان (تا وقتی خودتون عوضش کنید)"), ('1m', "۱ ماه"), ('3m', "۳ ماه"),
                ('6m', "۶ ماه"), ('year', "تا آخرِ امسال (%s)" % day_label(end_of_year(today), today))]
    return {
        'starts': starts,
        'ends': ends,
        'start': values.get('start') or 'today',
        'end': values.get('end') or '',
        'days': [(d, to_fa_digits(d)) for d in range(1, 32)],
        'months': list(enumerate(JALALI_MONTHS_FA, start=1)),
        'years': [(y, to_fa_digits(y)) for y in (jy, jy + 1)],
        'custom': values,
    }


def _custom(post, prefix):
    day, month, year = (to_int(post.get('%s_%s' % (prefix, part))) for part in ('day', 'month', 'year'))
    if not (day and month and year):
        return None, prefix + '_bad'
    try:
        return jalali_date(year, month, day), None
    except ValueError as e:
        return None, prefix + ('_day' if e.args and e.args[0] == 'day' else '_bad')


def dates_values(start, end):
    """What read_dates would need to give back these dates, for a form opened to change them.
    A start already past becomes today, since a change cannot start in the past."""
    today = tehran_today()
    start = max(start, today) if start else today
    values = {}
    if start == today:
        values['start'] = 'today'
    else:
        jy, jm, jd = _jalali(start)
        values.update({'start': 'custom', 'start_day': str(jd), 'start_month': str(jm), 'start_year': str(jy)})
    if not end:
        values['end'] = 'none'
    else:
        jy, jm, jd = _jalali(max(end, start))
        values.update({'end': 'custom', 'end_day': str(jd), 'end_month': str(jm), 'end_year': str(jy)})
    return values


def read_dates(post):
    """(start, end, error key) from the date buttons. `end` None means no end."""
    today = tehran_today()
    start_key = post.get('start')
    if start_key == 'today':
        start = today
    elif start_key == 'week':
        start = next_saturday(today)
    elif start_key == 'month':
        start = first_of_next_month(today)
    elif start_key == 'custom':
        start, error = _custom(post, 'start')
        if error:
            return None, None, error
    else:
        return None, None, 'start_missing'
    if start < today:
        return None, None, 'start_past'

    end_key = post.get('end')
    if end_key == 'none':
        end = None
    elif end_key == '1d':
        end = start
    elif end_key == '1w':
        end = start + timedelta(days=6)
    elif end_key in ('1m', '3m', '6m'):
        end = add_months(start, int(end_key[0])) - timedelta(days=1)
    elif end_key == 'year':
        end = end_of_year(start)
    elif end_key == 'custom':
        end, error = _custom(post, 'end')
        if error:
            return None, None, error
    else:
        return None, None, 'end_missing'
    if end and end < start:
        return None, None, 'order'
    return start, end, None


def dates_text(start, end, today=None):
    """«از ۱ مهر تا ۳۰ مهر» or «از ۱ مهر، بدون پایان»."""
    if not start:
        return ""
    if not end:
        return "از %s، بدون پایان" % day_label(start, today)
    return "از %s تا %s" % (day_label(start, today), day_label(end, today))


__all__ = ['DATE_ERRORS', 'date_widget', 'dates_text', 'day_label', 'jalali_to_gregorian', 'parse_jalali',
           'read_dates', 'tehran_today', 'to_int']
