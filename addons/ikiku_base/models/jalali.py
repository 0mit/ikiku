# Part of iKiKu. Licensed under AGPL-3.0.
"""Jalali (Solar Hijri) <-> Gregorian conversion.

Vendored deliberately. This is ~60 lines of arithmetic with no state, and the
alternative is a pip dependency fetched over a filtered network -- a build that
fails at the worst possible moment. See the build map, "Jalali".

The ledger stores Gregorian/UTC always. These functions run at the boundary:
portal rendering and portal input. A Jalali string in a database column is a bug.
"""

JALALI_MONTHS_FA = [
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
]
_FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_G_DAYS_IN_MONTH = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]


def gregorian_to_jalali(gy, gm, gd):
    if gy > 1600:
        jy = 979
        gy -= 1600
    else:
        jy = 0
        gy -= 621
    gy2 = gy + 1 if gm > 2 else gy
    days = (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100) + ((gy2 + 399) // 400) \
        - 80 + gd + _G_DAYS_IN_MONTH[gm - 1]
    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + days // 31
        jd = 1 + days % 31
    else:
        jm = 7 + (days - 186) // 30
        jd = 1 + (days - 186) % 30
    return jy, jm, jd


def jalali_to_gregorian(jy, jm, jd):
    if jy > 979:
        gy = 1600
        jy -= 979
    else:
        gy = 621
    days = (365 * jy) + ((jy // 33) * 8) + ((jy % 33 + 3) // 4) + 78 + jd \
        + ((jm - 1) * 31 if jm < 7 else ((jm - 7) * 30) + 186)
    gy += 400 * (days // 146097)
    days %= 146097
    if days > 36524:
        days -= 1
        gy += 100 * (days // 36524)
        days %= 36524
        if days >= 365:
            days += 1
    gy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        gy += (days - 1) // 365
        days = (days - 1) % 365
    gd = days + 1
    leap = (gy % 4 == 0 and gy % 100 != 0) or (gy % 400 == 0)
    months = [0, 31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gm = 0
    while gm < 13 and gd > months[gm]:
        gd -= months[gm]
        gm += 1
    return gy, gm, gd


def is_jalali_leap(jy):
    return ((jy + 12) % 33) % 4 == 1


def to_fa_digits(text):
    return str(text).translate(str.maketrans("0123456789", _FA_DIGITS))


def format_jalali(date_value, with_month_name=True, fa_digits=True):
    """A date object -> a Persian string. Absolute dates only, never relative."""
    if not date_value:
        return ""
    jy, jm, jd = gregorian_to_jalali(date_value.year, date_value.month, date_value.day)
    if with_month_name:
        out = "%d %s %d" % (jd, JALALI_MONTHS_FA[jm - 1], jy)
    else:
        out = "%04d/%02d/%02d" % (jy, jm, jd)
    return to_fa_digits(out) if fa_digits else out
