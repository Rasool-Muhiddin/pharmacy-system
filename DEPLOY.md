# دليل نشر مشروع Django على Ubuntu 24.04 (Hetzner)

هذا الدليل يغطي النشر الكامل من صفر (سيرفر جديد) إلى تطبيق يعمل خلف Nginx و Gunicorn،
مع PostgreSQL محلي، Redis، Cloudflare (Full strict)، Sentry، ونسخ احتياطي تلقائي إلى R2.

**الدومين المستخدم في هذا الدليل:** `tera-software1.com`
**مسار المشروع المستخدم:** `/var/www/pharmacy`
**موديول WSGI:** `clinic_project.wsgi:application`

عدّل هذي القيم في كل الأوامر أدناه لو غيّرتها.

---

## 1. تحديث النظام وتثبيت الحزم الأساسية

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-pip python3-venv nginx redis-server \
    postgresql postgresql-contrib git curl ufw
```

تأكد من تشغيل الخدمات الأساسية:
```bash
sudo systemctl enable --now postgresql
sudo systemctl enable --now redis-server
sudo systemctl enable --now nginx
```

---

## 2. إعداد الجدار الناري (UFW)

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'   # يفتح 80 و443
sudo ufw enable
sudo ufw status
```

⚠️ لا تفتح أي منفذ آخر (خصوصًا 5432 لـ PostgreSQL أو 6379 لـ Redis) للإنترنت — يجب أن يبقيا مسموحين فقط محليًا (localhost).

---

## 3. إنشاء مستخدم وقاعدة بيانات PostgreSQL

```bash
sudo -u postgres psql
```

داخل الـ psql shell:
```sql
CREATE DATABASE clinic_db;
CREATE USER clinic_user WITH PASSWORD 'ضع-كلمة-مرور-قوية-هنا';
ALTER ROLE clinic_user SET client_encoding TO 'utf8';
ALTER ROLE clinic_user SET default_transaction_isolation TO 'read committed';
ALTER ROLE clinic_user SET timezone TO 'Asia/Baghdad';
GRANT ALL PRIVILEGES ON DATABASE clinic_db TO clinic_user;
\q
```

احفظ اسم القاعدة، المستخدم، وكلمة المرور — ستحتاجها في `DATABASE_URL` بالخطوة 6.

---

## 4. استنساخ المشروع وإعداد البيئة الافتراضية

```bash
sudo mkdir -p /var/www/pharmacy
sudo chown $USER:$USER /var/www/pharmacy
cd /var/www/pharmacy

git clone <رابط-مستودع-Git-الخاص-بك> .

python3 -m venv venv
source venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
```

---

## 5. تثبيت أدوات النسخ الاحتياطي (لسكربت R2)

```bash
sudo apt install -y awscli
```

---

## 6. إعداد ملف `.env`

```bash
cp .env.example .env
nano .env
```

املأ القيم الفعلية:
```
SECRET_KEY=<ولّد مفتاحًا عشوائيًا قويًا، لا تستخدم قيمة افتراضية>
DEBUG=False
ALLOWED_HOSTS=tera-software1.com,www.tera-software1.com
CSRF_TRUSTED_ORIGINS=https://tera-software1.com,https://www.tera-software1.com
ADMIN_URL=<مسار عشوائي غير admin/, مثال: mgmt-7f2a9c/>
DATABASE_URL=postgres://clinic_user:كلمة-المرور@localhost:5432/clinic_db
REDIS_URL=redis://127.0.0.1:6379/1
SENTRY_DSN=<الصق DSN الحقيقي من لوحة Sentry>
```

لتوليد `SECRET_KEY` قوي:
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(50))"
```

صلاحيات صارمة على `.env`:
```bash
chmod 600 .env
```

---

## 7. تطبيق الترحيلات وجمع الملفات الثابتة

```bash
source venv/bin/activate
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py createsuperuser
```

---

## 8. تثبيت شهادة Cloudflare Origin Certificate

```bash
sudo mkdir -p /etc/ssl/cloudflare
sudo nano /etc/ssl/cloudflare/cert.pem
# الصق محتوى Origin Certificate الذي حفظته مسبقًا، احفظ (Ctrl+O, Enter) واخرج (Ctrl+X)

sudo nano /etc/ssl/cloudflare/key.pem
# الصق محتوى Private Key، احفظ واخرج بنفس الطريقة

sudo chmod 600 /etc/ssl/cloudflare/key.pem
sudo chmod 644 /etc/ssl/cloudflare/cert.pem
```

تأكد من تفعيل **Full (strict)** في لوحة Cloudflare: `SSL/TLS → Overview`.

---

## 9. إعداد Gunicorn (systemd)

```bash
sudo nano /etc/systemd/system/gunicorn.service
# الصق محتوى ملف gunicorn.service الجاهز (تحقق من المسارات: /var/www/pharmacy)
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable gunicorn
sudo systemctl start gunicorn
sudo systemctl status gunicorn
```

تأكد من عدم وجود أخطاء، ومن وجود ملف الـ socket:
```bash
ls -la /var/www/pharmacy/gunicorn.sock
```

---

## 10. إعداد Nginx

```bash
sudo nano /etc/nginx/sites-available/tera-software1.com
# الصق محتوى ملف nginx.conf الجاهز

sudo ln -s /etc/nginx/sites-available/tera-software1.com /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default   # إزالة الإعداد الافتراضي

sudo nginx -t   # اختبار صحة الإعداد قبل إعادة التشغيل
sudo systemctl reload nginx
```

---

## 11. ربط الدومين بالسيرفر (DNS في Cloudflare)

من لوحة Cloudflare → دومينك → DNS:
- أضف سجل `A` باسم `@` يشير إلى IP السيرفر (Hetzner)، مع تفعيل **Proxy (السحابة البرتقالية)**
- أضف سجل `A` باسم `www` بنفس IP السيرفر، مع تفعيل Proxy أيضًا

انتظر بضع دقائق لانتشار DNS، ثم جرب:
```
https://tera-software1.com
```

---

## 12. تفعيل HSTS (بعد التأكد من نجاح HTTPS فقط)

بعد ما تتأكد إن الموقع يعمل بشكل صحيح عبر HTTPS بدون مشاكل، عدّل `.env`:
```
SECURE_HSTS_SECONDS=31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS=True
```
ثم أعد تشغيل Gunicorn:
```bash
sudo systemctl restart gunicorn
```

⚠️ لا تفعّل هذا قبل التأكد التام من عمل HTTPS، لأن HSTS يجبر المتصفح على HTTPS لمدة سنة كاملة حتى لو رجعت لاحقًا لـ HTTP.

---

## 13. إعداد النسخ الاحتياطي التلقائي (R2)

```bash
sudo mkdir -p /root/backups
sudo nano /root/backups/.env.backup
```

الصق فيه:
```
DATABASE_URL=postgres://clinic_user:كلمة-المرور@localhost:5432/clinic_db
R2_ACCESS_KEY_ID=<من لوحة Cloudflare>
R2_SECRET_ACCESS_KEY=<من لوحة Cloudflare>
R2_ENDPOINT_URL=https://6dd0e567cb13bb663480c6bc49a4b66a.r2.cloudflarestorage.com
R2_BUCKET_NAME=pharmacy-backups
```

```bash
sudo chmod 600 /root/backups/.env.backup

sudo cp backup-db.sh /usr/local/bin/backup-db.sh
sudo chmod +x /usr/local/bin/backup-db.sh

# اختبار يدوي أولاً
sudo /usr/local/bin/backup-db.sh
```

بعد التأكد من نجاح النسخة التجريبية، جدوله:
```bash
sudo crontab -e -u root
```
أضف السطر:
```
0 3 * * * /usr/local/bin/backup-db.sh >> /var/log/backup-db.log 2>&1
```

---

## 14. مراقبة الموقع (UptimeRobot)

1. أنشئ حساب مجاني على https://uptimerobot.com
2. أضف Monitor جديد من نوع HTTP(s)، الرابط: `https://tera-software1.com/healthz/`
3. اختر فترة الفحص (5 دقائق كافية للخطة المجانية)
4. أضف بريدك الإلكتروني للتنبيهات عند توقف الموقع

---

## 15. قائمة التحقق النهائية (Checklist)

- [ ] `https://tera-software1.com` يفتح بدون تحذير شهادة
- [ ] `https://tera-software1.com/healthz/` يرجع استجابة ناجحة
- [ ] تسجيل الدخول للوحة الإدارة يعمل عبر `ADMIN_URL` المخصص (وليس `/admin/`)
- [ ] `python manage.py check --deploy` لا يظهر تحذيرات حرجة
- [ ] Sentry يستقبل الأخطاء (جرّب استثناء تجريبي والتحقق من ظهوره في لوحة Sentry)
- [ ] `sudo /usr/local/bin/backup-db.sh` نجح والملف ظهر في R2 bucket
- [ ] `sudo systemctl status gunicorn nginx postgresql redis-server` كلها `active (running)`
- [ ] UptimeRobot يراقب `/healthz/` بنجاح
- [ ] `DEBUG=False` في `.env` الفعلي على السيرفر (تأكيد نهائي)

---

## أوامر مفيدة لاحقًا (صيانة وتشخيص)

```bash
# سجلات Gunicorn
sudo journalctl -u gunicorn -f

# سجلات Nginx
sudo tail -f /var/log/nginx/error.log

# إعادة تشغيل بعد تحديث الكود
cd /var/www/pharmacy
source venv/bin/activate
git pull
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
sudo systemctl restart gunicorn
```