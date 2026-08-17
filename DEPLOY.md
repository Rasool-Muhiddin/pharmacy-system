# دليل نشر مشروع Django على Ubuntu 24.04 (Hetzner)

هذا المستند يحتوي على الخطوات العملية الكاملة لنشر المشروع من الصفر باستخدام Nginx و Gunicorn و Redis و PostgreSQL.

---

## 1. تحديث النظام وتثبيت الحزم الأساسية

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-pip python3-venv nginx redis-server postgresql postgresql-contrib git curl