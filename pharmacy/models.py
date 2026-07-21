import uuid
from django.db import models
from django.contrib.auth.models import User

# =======================================================
# 1️⃣ جدول الصيدليات (المشتركين في نظامك)
# =======================================================
class PharmacyBranch(models.Model):
    name = models.CharField(max_length=255, verbose_name="اسم الصيدلية")
    is_active = models.BooleanField(default=True, verbose_name="حالة الاشتراك")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الاشتراك")

    def __str__(self):
        return self.name or "صيدلية بدون اسم"

# =======================================================
# 2️⃣ جدول ملف المستخدم (لربط المستخدم بصيدلية معينة وصلاحياته)
# =======================================================
class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    pharmacy = models.ForeignKey(PharmacyBranch, on_delete=models.CASCADE, related_name='users', verbose_name="الصيدلية التابع لها")
    is_pharmacy_owner = models.BooleanField(default=False, verbose_name="هل هو صاحب الصيدلية؟")

    def __str__(self):
        pharmacy_name = self.pharmacy.name if self.pharmacy else "بدون صيدلية"
        return f"{self.user.username} - {pharmacy_name}"

# =======================================================
# 3️⃣ جدول الأدوية (محصن ضد تكرار الباركود الفارغ والأسعار)
# =======================================================
class Medicine(models.Model):
    CATEGORY_CHOICES = [
        ('tablet', '💊 حبوب / كبسول'),
        ('syrup', '🧪 شراب / معلق'),
        ('injection', '💉 حقن / فيال / أمبول'),
        ('ointment', '🧴 مرهم / كريم / جيل'),
        ('drops_eye_ear', '👁️ قطرات عين / أذن'),
        ('drops_nasal', '👃 قطرات / بخاخ أنف'),
        ('suppository', ' تحاميل / لبوس'),
        ('supplement_vitamin', '🍏 فيتامينات / مكملات غذائية'),
        ('tonic_energy', '⚡ مقويات / منشطات'),
        ('powder_sachet', '🥛 بودرة / فوار'),
        ('medical_device', '🩺 مستلزمات طبية / أجهزة'),
        ('other', '📦 أخرى'),
    ]

    pharmacy = models.ForeignKey(PharmacyBranch, on_delete=models.CASCADE, related_name='medicines', verbose_name="الصيدلية")
     
    trade_name = models.CharField(max_length=200, verbose_name="الاسم التجاري")
    scientific_name = models.CharField(max_length=200, verbose_name="الاسم العلمي")
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='tablet', verbose_name="نوع الدواء")
    quantity = models.IntegerField(default=0, verbose_name="الكمية المتوفرة")
    buy_price = models.IntegerField(default=0, verbose_name="سعر الشراء (د.ع)")
    sell_price = models.IntegerField(default=0, verbose_name="سعر البيع (د.ع)")
    expiry_date = models.DateField(verbose_name="تاريخ انتهاء الصلاحية")
    shelf_location = models.CharField(max_length=50, blank=True, null=True, verbose_name="مكان الرف")
    is_damaged = models.BooleanField(default=False, verbose_name="هل الدواء تالف/معزول؟")
    barcode = models.CharField(max_length=50, null=True, blank=True, verbose_name="باركود الدواء")

    class Meta:
        unique_together = ('pharmacy', 'barcode')

    def save(self, *args, **kwargs):
        # 🛡️ تحويل الباركود الفارغ أو النص المكون من مسافات إلى None لمنع التصادم في unique_together
        if self.barcode is not None and not str(self.barcode).strip():
            self.barcode = None
        super().save(*args, **kwargs)

    def __str__(self):
        pharmacy_name = self.pharmacy.name if self.pharmacy else "عام"
        return f"{self.trade_name} ({self.scientific_name}) - {pharmacy_name}"

# =======================================================
# 4️⃣ جدول المبيعات الفردية
# =======================================================
class Sale(models.Model):
    pharmacy = models.ForeignKey(PharmacyBranch, on_delete=models.CASCADE, related_name='sales', null=True, blank=True, verbose_name="الصيدلية")
    medicine = models.ForeignKey('Medicine', on_delete=models.CASCADE, verbose_name="الدواء المباع")
    quantity_sold = models.IntegerField(default=1, verbose_name="الكمية المباعة")
    total_price = models.IntegerField(default=0, verbose_name="إجمالي سعر البيع")
    sold_at = models.DateTimeField(auto_now_add=True, verbose_name="وقت عملية البيع")
    is_refunded = models.BooleanField(default=False)
    cashier = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='sales', verbose_name="الكاشير")

    def __str__(self):
        med_name = self.medicine.trade_name if self.medicine else "دواء محذوف"
        return f"بيعة: {med_name} x {self.quantity_sold}"

# =======================================================
# 5️⃣ أ - جدول المذاخر والمكاتب العلمية
# =======================================================
class PharmacySupplier(models.Model):
    pharmacy = models.ForeignKey(PharmacyBranch, on_delete=models.CASCADE, related_name='suppliers', verbose_name="الصيدلية")
    name = models.CharField(max_length=255, verbose_name="اسم المذخر / المكتب")
    phone = models.CharField(max_length=50, blank=True, null=True, verbose_name="رقم الهاتف")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('pharmacy', 'name')

    def __str__(self):
        pharmacy_name = self.pharmacy.name if self.pharmacy else "عام"
        return f"{self.name} ({pharmacy_name})"

# =======================================================
# 5️⃣ ب - جدول النواقص
# =======================================================
class MissingMedicine(models.Model):
    pharmacy = models.ForeignKey(PharmacyBranch, on_delete=models.CASCADE, related_name='missing_medicines', null=True, blank=True)
    medicine = models.ForeignKey('Medicine', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="الدواء المرتبط بالمخزن")
    medicine_name = models.CharField(max_length=200, verbose_name="اسم الدواء الناقص")
    supplier = models.ForeignKey(PharmacySupplier, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="المذخر الموجه له الطلب")
    notes = models.TextField(blank=True, null=True, verbose_name="ملاحظات الصيدلي")
    requested_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.medicine_name or "دواء ناقص"

# =======================================================
# 6️⃣ جدول الفواتير الرئيسي (محصن ضد التصادم والتزامن)
# =======================================================
class Invoice(models.Model):
    pharmacy = models.ForeignKey(PharmacyBranch, on_delete=models.CASCADE, related_name='invoices', null=True, blank=True)
    invoice_number = models.CharField(max_length=50, blank=True)
    cashier = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='invoices', verbose_name="الكاشير المسؤول")
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.0, verbose_name="المجموع قبل الخصم")
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0.0, verbose_name="قيمة الخصم المالي")
    final_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.0, verbose_name="الصافي المدفوع فعلياً")
    created_at = models.DateTimeField(auto_now_add=True)
    is_refunded = models.BooleanField(default=False)

    class Meta:
        unique_together = ('pharmacy', 'invoice_number')

    def save(self, *args, **kwargs):
        if not self.invoice_number:
            try:
                last_invoice = Invoice.objects.filter(pharmacy=self.pharmacy).order_by('id').last()
                
                if last_invoice and last_invoice.invoice_number:
                    try:
                        last_num = int(last_invoice.invoice_number.split('-')[1])
                        next_num = last_num + 1
                    except (ValueError, IndexError):
                        next_num = Invoice.objects.filter(pharmacy=self.pharmacy).count() + 1
                else:
                    next_num = 1
                    
                self.invoice_number = f"INV-{next_num}"
            except Exception:
                # 🛡️ خطة طوارئ في حال حدث تضارب في التوليد لضمان عدم انهيار السيرفر أبداً
                self.invoice_number = f"INV-{uuid.uuid4().hex[:6].upper()}"
                
        super().save(*args, **kwargs)

    def __str__(self):
        pharmacy_name = self.pharmacy.name if self.pharmacy else 'عام'
        return f"فاتورة {self.invoice_number} - الصيدلية: {pharmacy_name} - الصافي: {self.final_amount} د.ع"

# =======================================================
# 7️⃣ جدول تفاصيل عناصر الفاتورة
# =======================================================
class InvoiceItem(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='items')
    medicine = models.ForeignKey('Medicine', on_delete=models.CASCADE)
    quantity = models.IntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    total_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)

    def __str__(self):
        med_name = self.medicine.trade_name if self.medicine else "دواء غير محدد"
        inv_num = self.invoice.invoice_number if self.invoice else "بدون فاتورة"
        return f"{med_name} x {self.quantity} in {inv_num}"

# =======================================================
# 8️⃣ جدول الأدوية التالفة
# =======================================================
class DamagedMedicine(models.Model):
    # 🎯 خيارات موحدة ومتطابقة تماماً مع inventory.html و damaged_list.html
    DAMAGE_REASONS = [
        ('expired', '📆 منتهي الصلاحية'),
        ('broken', '💔 كسر وضرر'),
        ('spoiled', '☀️ سوء خزن'),
        ('withdrawn', '🚫 سحب وزاري'),
        ('other', '📦 أسباب أخرى'),
    ]

    pharmacy = models.ForeignKey(PharmacyBranch, on_delete=models.CASCADE, related_name='damaged_medicines', verbose_name="الصيدلية")
    medicine = models.ForeignKey(Medicine, on_delete=models.CASCADE, related_name='damaged_records', verbose_name="الدواء")
    quantity_damaged = models.IntegerField(default=1, verbose_name="الكمية التالفة")
    reason = models.CharField(max_length=20, choices=DAMAGE_REASONS, default='expired', verbose_name="سبب التلف")
    notes = models.TextField(blank=True, null=True, verbose_name="ملاحظات إضافية")
    damaged_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ ووقت الإتلاف")

    # 💡 خاصية حاسبة لخسارة العملية بأمان دون الحاجة لفلاتر Django خارجية
    @property
    def total_loss(self):
        if self.medicine and self.medicine.buy_price:
            return self.quantity_damaged * self.medicine.buy_price
        return 0

    def __str__(self):
        med_name = self.medicine.trade_name if self.medicine else "دواء غير محدد"
        return f"تلف: {med_name} x {self.quantity_damaged}"