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
        return self.name

# =======================================================
# 2️⃣ جدول ملف المستخدم (لربط المستخدم بصيدلية معينة وصلاحياته)
# =======================================================
class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    pharmacy = models.ForeignKey(PharmacyBranch, on_delete=models.CASCADE, related_name='users', verbose_name="الصيدلية التابع لها")
    is_pharmacy_owner = models.BooleanField(default=False, verbose_name="هل هو صاحب الصيدلية؟")

    def __str__(self):
        return f"{self.user.username} - {self.pharmacy.name}"

# =======================================================
# 3️⃣ جدول الأدوية (تم تعديل قيد الباركود ليتناسب مع تعدد الصيدليات)
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
    buy_price = models.IntegerField(verbose_name="سعر الشراء (د.ع)")
    sell_price = models.IntegerField(verbose_name="سعر البيع (د.ع)")
    expiry_date = models.DateField(verbose_name="تاريخ انتهاء الصلاحية")
    shelf_location = models.CharField(max_length=50, blank=True, null=True, verbose_name="مكان الرف")
    is_damaged = models.BooleanField(default=False, verbose_name="هل الدواء تالف/معزول؟")
    barcode = models.CharField(max_length=50, null=True, blank=True, verbose_name="باركود الدواء")

    # 🛠️ قيد ذكي: منع تكرار الباركود داخل الصيدلية الواحدة، والسماح بتكراره بين الصيدليات المختلفة
    class Meta:
        unique_together = ('pharmacy', 'barcode')

    def __str__(self):
        return f"{self.trade_name} ({self.scientific_name}) - {self.pharmacy.name}"

# =======================================================
# 4️⃣ جدول المبيعات الفردية (تم إضافة حقل الصيدلية لتسريع التقارير)
# =======================================================
class Sale(models.Model):
    pharmacy = models.ForeignKey(PharmacyBranch, on_delete=models.CASCADE, related_name='sales', null=True, blank=True, verbose_name="الصيدلية")
    medicine = models.ForeignKey('Medicine', on_delete=models.CASCADE, verbose_name="الدواء المباع")
    quantity_sold = models.IntegerField(verbose_name="الكمية المباعة")
    total_price = models.IntegerField(verbose_name="إجمالي سعر البيع")
    sold_at = models.DateTimeField(auto_now_add=True, verbose_name="وقت عملية البيع")
    is_refunded = models.BooleanField(default=False)
    cashier = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='sales', verbose_name="الكاشير")

    def __str__(self):
        return f"بيعة: {self.medicine.trade_name} x {self.quantity_sold}"

# =======================================================
# 5️⃣ أ - جدول المذاخر والمكاتب العلمية (جديد)
# =======================================================
class PharmacySupplier(models.Model):
    pharmacy = models.ForeignKey(PharmacyBranch, on_delete=models.CASCADE, related_name='suppliers', verbose_name="الصيدلية")
    name = models.CharField(max_length=255, verbose_name="اسم المذخر / المكتب")
    phone = models.CharField(max_length=50, blank=True, null=True, verbose_name="رقم الهاتف")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('pharmacy', 'name') # منع تكرار نفس اسم المذخر لنفس الصيدلية

    def __str__(self):
        return f"{self.name} ({self.pharmacy.name})"



# =======================================================
# 5️⃣ جدول النواقص
# =======================================================
class MissingMedicine(models.Model):
    pharmacy = models.ForeignKey(PharmacyBranch, on_delete=models.CASCADE, related_name='missing_medicines', null=True, blank=True)
    
    # إذا كان الدواء تم تحويله تلقائياً من المخزن نربطه هنا
    medicine = models.ForeignKey('Medicine', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="الدواء المرتبط بالمخزن")
    
    # إذا كان الدواء جديداً يُكتب اسمه هنا
    medicine_name = models.CharField(max_length=200, verbose_name="اسم الدواء الناقص")
    
    # ربط الناقص بالمذخر (يمكن أن يكون فارغاً حتى يحدده الصيدلي لاحقاً)
    supplier = models.ForeignKey(PharmacySupplier, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="المذخر الموجه له الطلب")
    
    notes = models.TextField(blank=True, null=True, verbose_name="ملاحظات الصيدلي")
    requested_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.medicine_name

# =======================================================
# 6️⃣ جدول الفواتير الرئيسي (تم التعديل ليدعم تعدد الصيدليات)
# =======================================================
class Invoice(models.Model):
    pharmacy = models.ForeignKey(PharmacyBranch, on_delete=models.CASCADE, related_name='invoices', null=True, blank=True)
    
    # 🟢 تم إزالة unique=True لأن الرقم سيتكرر (مثل: كل صيدلية سيكون عندها فاتورة رقم 1)
    invoice_number = models.CharField(max_length=20, blank=True)
    
    cashier = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='invoices', verbose_name="الكاشير المسؤول")
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.0, verbose_name="المجموع قبل الخصم")
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0.0, verbose_name="قيمة الخصم المالي")
    final_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.0, verbose_name="الصافي المدفوع فعلياً")
    created_at = models.DateTimeField(auto_now_add=True)
    is_refunded = models.BooleanField(default=False)

    class Meta:
        # 🟢 قيد ذكي: يمنع تكرار نفس رقم الفاتورة داخل "نفس الصيدلية" فقط، ويسمح بتكراره في الصيدليات الأخرى
        unique_together = ('pharmacy', 'invoice_number')

    def save(self, *args, **kwargs):
        if not self.invoice_number:
            # 🟢 1. الفلترة حسب الصيدلية الحالية فقط لجلب آخر فاتورة خاصة بها
            last_invoice = Invoice.objects.filter(pharmacy=self.pharmacy).order_by('id').last()
            
            if last_invoice:
                # 🟢 2. استخراج الرقم الحقيقي من نص الفاتورة (مثلاً INV-16 يأخذ منها 16) ويضيف عليه 1
                try:
                    last_num = int(last_invoice.invoice_number.split('-')[1])
                    next_num = last_num + 1
                except (ValueError, IndexError):
                    # كخطة بديلة حاسبة في حال كان النص غير متوافق
                    next_num = Invoice.objects.filter(pharmacy=self.pharmacy).count() + 1
            else:
                # 🟢 3. إذا كانت الصيدلية جديدة تماماً ولا تملك أي فاتورة، ابدأ من 1
                next_num = 1    
                
            self.invoice_number = f"INV-{next_num}"
            
        super().save(*args, **kwargs)

    def __str__(self):
        return f"فاتورة {self.invoice_number} - الصيدلية: {self.pharmacy.name if self.pharmacy else 'عام'} - الصافي: {self.final_amount} د.ع"

# =======================================================
# 7️⃣ جدول تفاصيل عناصر الفاتورة
# =======================================================
class InvoiceItem(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='items')
    medicine = models.ForeignKey('Medicine', on_delete=models.CASCADE)
    quantity = models.IntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    total_price = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.medicine.trade_name} x {self.quantity} in {self.invoice.invoice_number}"

# =======================================================
# 8️⃣ جدول الأدوية التالفة
# =======================================================
class DamagedMedicine(models.Model):
    DAMAGE_REASONS = [
        ('heat', '🌡️ تلف بسبب الحرارة / انقطاع الكهرباء'),
        ('storage', '📦 تلف بسبب سوء التخزين / الرطوبة'),
        ('physical', '💥 كسر / تلف فيزيائي للمنتج'),
        ('other', '🌀 أسباب أخرى'),
    ]

    pharmacy = models.ForeignKey(PharmacyBranch, on_delete=models.CASCADE, related_name='damaged_medicines', verbose_name="الصيدلية")
    medicine = models.ForeignKey(Medicine, on_delete=models.CASCADE, related_name='damaged_records', verbose_name="الدواء")
    quantity_damaged = models.IntegerField(verbose_name="الكمية التالفة")
    reason = models.CharField(max_length=20, choices=DAMAGE_REASONS, default='heat', verbose_name="سبب التلف")
    notes = models.TextField(blank=True, null=True, verbose_name="ملاحظات إضافية")
    damaged_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ ووقت الإتلاف")

    def __str__(self):
        return f"تلف: {self.medicine.trade_name} x {self.quantity_damaged}"