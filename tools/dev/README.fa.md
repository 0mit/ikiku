# ایکیکو روی کامپیوترِ خودتان

برای دیدن و تغییر دادن، نه برای سرورِ واقعی. همان تصویرهایی که سایتِ اصلی با آن‌ها کار می‌کند
(`postgres:17` و `odoo:19`)، کدِ همین مخزن، و قالب‌ها و استایل‌هایی که با هر بار تازه‌کردنِ صفحه از
روی دیسک خوانده می‌شوند؛ پس تغییرِ یک فایلِ `.xml` یا `.scss` با یک رفرش دیده می‌شود.

فقط Docker لازم است (Docker Desktop روی مک و ویندوز). همهٔ دستورها از ریشهٔ مخزن اجرا می‌شوند.

```sh
# یک بار: ساختنِ پایگاه‌داده با همهٔ ماژول‌ها، زبانِ فارسی و جاهای ایران (حدود ۳ دقیقه)
docker compose -f tools/dev/compose.yml run --rm init

# چند آدم و مجموعهٔ ساختگی برای دیدنِ صفحه‌ها
docker compose -f tools/dev/compose.yml run --rm -T odoo odoo shell -c /etc/odoo/odoo.conf -d ikiku < tools/dev/sample_data.py

# روشن کردن: http://localhost:8069
docker compose -f tools/dev/compose.yml up -d odoo

# آزمون‌ها، در پایگاه‌داده‌ای جدا (حدود ۳ دقیقه؛ باید «0 failed, 0 error(s)» بگوید)
docker compose -f tools/dev/compose.yml run --rm tests

# بررسیِ ایستا، پیش از هر commit (باید «0 error(s)» بگوید)
python3 tools/validate.py

# خاموش کردن؛ با -v همه‌چیز پاک می‌شود و از اول ساخته می‌شود
docker compose -f tools/dev/compose.yml down
```

- ورود به بخشِ مدیریت: `admin` / `admin` در http://localhost:8069/odoo
- حساب‌های ساختگی: کارجو `sample-ki` با رمز `sample-ki-pass`، دارندهٔ مجموعه `sample-ku` با رمز `sample-ku-pass`
- اگر پورتِ ۸۰۶۹ گرفته است: `IKIKU_PORT=8169 docker compose -f tools/dev/compose.yml up -d odoo`
- ورود با پیامک اینجا خاموش است؛ ثبت‌نام و ورود با ایمیل و رمز کار می‌کند.
- پس از تغییرِ کدِ پایتون (نه قالب یا استایل): `docker compose -f tools/dev/compose.yml restart odoo`؛
  پس از افزودنِ فیلد یا فایلِ تازه: یک بار `init` را با `-u ikiku_portal` به‌جای `-i` اجرا کنید.
