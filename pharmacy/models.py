import secrets
import uuid
from django.db import models, transaction
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.core.exceptions import ValidationError
from django.utils import timezone
def generate_desktop_license_code():
    """إنشاء رمز تفعيل آمن وفريد لنسخة سطح المكتب."""
    return f"TERA-{secrets.token_urlsafe(24).upper()}"

# =======================================================
# 1️⃣ جدول الصيدليات (المشتركين في نظامك)
# =======================================================
class PharmacyBranch(models.Model):
    name = models.CharField(max_length=255, verbose_name="اسم الصيدلية")
    is_active = models.BooleanField(default=True, verbose_name="حالة الاشتراك")
    invoice_sequence = models.PositiveBigIntegerField(
        default=0,
        editable=False,
        verbose_name="آخر رقم فاتورة صادر",
    )
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
    quantity = models.IntegerField(default=0, validators=[MinValueValidator(0)], verbose_name="الكمية المتوفرة")
    buy_price = models.IntegerField(default=0, validators=[MinValueValidator(0)], verbose_name="سعر الشراء (د.ع)")
    sell_price = models.IntegerField(default=0, validators=[MinValueValidator(0)], verbose_name="سعر البيع (د.ع)")
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
    quantity_sold = models.IntegerField(default=1, validators=[MinValueValidator(1)], verbose_name="الكمية المباعة")
    total_price = models.IntegerField(default=0, validators=[MinValueValidator(0)], verbose_name="إجمالي سعر البيع")
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
        ordering = ['name']
        unique_together = ('pharmacy', 'name')

    def __str__(self):
        pharmacy_name = self.pharmacy.name if self.pharmacy else "عام"
        return f"{self.name} ({pharmacy_name})"

# =======================================================
# 6️⃣ جدول الفواتير الرئيسي (محصن ضد التصادم والتزامن)
# =======================================================
class Invoice(models.Model):
    pharmacy = models.ForeignKey(PharmacyBranch, on_delete=models.CASCADE, related_name='invoices', null=True, blank=True)
    invoice_number = models.CharField(max_length=50, blank=True)
    cashier = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='invoices', verbose_name="الكاشير المسؤول")
    total_amount = models.IntegerField(default=0, validators=[MinValueValidator(0)], verbose_name="المجموع قبل الخصم")
    discount = models.IntegerField(default=0, validators=[MinValueValidator(0)], verbose_name="قيمة الخصم المالي")
    final_amount = models.IntegerField(default=0, validators=[MinValueValidator(0)], verbose_name="الصافي المدفوع فعلياً")
    created_at = models.DateTimeField(auto_now_add=True)
    is_refunded = models.BooleanField(default=False)

    class Meta:
        unique_together = ('pharmacy', 'invoice_number')

    def clean(self):
        # 🛡️ الخصم لا يجب أن يتجاوز المجموع قبل الخصم
        if self.discount and self.total_amount and self.discount > self.total_amount:
            raise ValidationError({'discount': 'قيمة الخصم لا يمكن أن تتجاوز المجموع قبل الخصم.'})

    def save(self, *args, **kwargs):
        if not self.invoice_number:
            if self.pharmacy_id:
                # قفل صف الصيدلية يجعل العداد متسلسلاً لكل صيدلية، حتى عند
                # تنفيذ عمليتي بيع متزامنتين أو إنشاء فاتورة من مسار آخر.
                with transaction.atomic():
                    pharmacy = PharmacyBranch.objects.select_for_update().get(
                        pk=self.pharmacy_id
                    )

                    # بعد تطبيق الـ migration سيكون العداد صفراً للفواتير
                    # القديمة؛ نهيئه مرة واحدة من أرقام INV الرقمية الموجودة.
                    if pharmacy.invoice_sequence == 0:
                        existing_numbers = Invoice.objects.filter(
                            pharmacy_id=pharmacy.pk
                        ).values_list('invoice_number', flat=True)
                        numeric_numbers = (
                            int(number[4:])
                            for number in existing_numbers
                            if number and number.startswith('INV-')
                            and number[4:].isdigit()
                        )
                        pharmacy.invoice_sequence = max(numeric_numbers, default=0)

                    pharmacy.invoice_sequence += 1
                    pharmacy.save(update_fields=['invoice_sequence'])
                    self.invoice_number = f"INV-{pharmacy.invoice_sequence}"

                    return super().save(*args, **kwargs)

            # هذا المسار مخصص فقط للفواتير الإدارية القديمة التي لا ترتبط
            # بصيدلية، ولا يدخل في تسلسل فواتير نقاط البيع.
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
    quantity = models.IntegerField(default=1, validators=[MinValueValidator(1)])
    unit_price = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    total_price = models.IntegerField(default=0, validators=[MinValueValidator(0)])

    def __str__(self):
        med_name = self.medicine.trade_name if self.medicine else "دواء غير محدد"
        inv_num = self.invoice.invoice_number if self.invoice else "بدون فاتورة"
        return f"{med_name} x {self.quantity} in {inv_num}"

# =======================================================
# 8️⃣ جدول الأدوية التالفة
# =======================================================
class DamagedMedicine(models.Model):
    DAMAGE_REASONS = [
        ('expired', '📆 منتهي الصلاحية'),
        ('broken', '💔 كسر وضرر'),
        ('spoiled', '☀️ سوء خزن'),
        ('withdrawn', '🚫 سحب وزاري'),
        ('quantity_correction', '✏️ تعديل كمية (إضافة خاطئة)'),
        ('other', '📦 أسباب أخرى'),
    ]

    pharmacy = models.ForeignKey(PharmacyBranch, on_delete=models.CASCADE, related_name='damaged_medicines', verbose_name="الصيدلية")
    medicine = models.ForeignKey(Medicine, on_delete=models.CASCADE, related_name='damaged_records', verbose_name="الدواء")
    quantity_damaged = models.IntegerField(default=1, validators=[MinValueValidator(1)], verbose_name="الكمية التالفة")
    unit_cost = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        editable=False,
        verbose_name="سعر شراء الوحدة وقت الإتلاف",
    )
    reason = models.CharField(max_length=20, choices=DAMAGE_REASONS, default='expired', verbose_name="سبب التلف")
    notes = models.TextField(blank=True, null=True, verbose_name="ملاحظات إضافية")
    damaged_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ ووقت الإتلاف")

    @property
    def total_loss(self):
        # 🛡️ عمليات "تعديل الكمية" ليست خسارة فعلية (كمية أُضيفت بالخطأ للمخزون)
        # لذا لا تُحتسب ضمن مجموع الخسائر المالية.
        if self.reason == 'quantity_correction':
            return 0
        return self.quantity_damaged * self.unit_cost

    def save(self, *args, **kwargs):
        # يحمي السجلات التي تُنشأ من Admin أو أي مسار آخر غير شاشة الإتلاف.
        if self._state.adding and not self.unit_cost and self.medicine_id:
            self.unit_cost = Medicine.objects.only('buy_price').get(
                pk=self.medicine_id
            ).buy_price
        super().save(*args, **kwargs)

    def __str__(self):
        med_name = self.medicine.trade_name if self.medicine else "دواء غير محدد"
        return f"تلف: {med_name} x {self.quantity_damaged}"

# =======================================================
# 9️⃣ جدول اشتراكات الصيدليات
# =======================================================
class Subscription(models.Model):
    PLAN_CHOICES = [
        ('free', '🆓 مجاني (تجريبي)'),
        ('silver', '🥈 الفضية'),
        ('gold', '🥇 الذهبية'),
        ('enterprise', '💎 ماسية / خاصة'),
    ]

    STATUS_CHOICES = [
        ('active', '✅ فعال'),
        ('expired', '❌ منتهي'),
        ('trial', '⏳ فترة تجريبية'),
        ('cancelled', '🚫 ملغى'),
    ]

    pharmacy = models.OneToOneField(PharmacyBranch, on_delete=models.CASCADE, related_name='subscription', verbose_name="الصيدلية")
    plan_type = models.CharField(max_length=20, choices=PLAN_CHOICES, default='free', verbose_name="نوع الخطة")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='trial', verbose_name="حالة الاشتراك")
    start_date = models.DateTimeField(default=timezone.now, verbose_name="تاريخ بداية الاشتراك")
    end_date = models.DateTimeField(verbose_name="تاريخ انتهاء الاشتراك")
    is_auto_renew = models.BooleanField(default=False, verbose_name="تجديد تلقائي")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def is_valid(self):
        """فحص سريع لمعرفة هل الاشتراك شغال ونافع حتى اللحظة"""
        return self.status in ['active', 'trial'] and self.end_date >= timezone.now()

    def __str__(self):
        return f"اشتراك {self.pharmacy.name} - الخطة: {self.get_plan_type_display()} ({self.get_status_display()})"

# =======================================================
# 🔟 جدول المدفوعات والفواتير المالية للاشتراكات
# =======================================================
class Payment(models.Model):
    PAYMENT_METHODS = [
        ('zain_cash', '📱 زين كاش'),
        ('qi_card', '💳 كي كارت / ماستر كارد'),
        ('fastpay', '⚡ فاست باي'),
        ('cash', '💵 نقداً للمندوب'),
        ('other', '🏦 تحويل بانكي / آخر'),
    ]

    STATUS_CHOICES = [
        ('success', '✅ ناجح'),
        ('pending', '⏳ قيد الانتظار'),
        ('failed', '❌ فاشل'),
    ]

    pharmacy = models.ForeignKey(PharmacyBranch, on_delete=models.CASCADE, related_name='payments', verbose_name="الصيدلية")
    subscription = models.ForeignKey(Subscription, on_delete=models.SET_NULL, null=True, blank=True, related_name='payments', verbose_name="الاشتراك المرتبط")
    amount = models.IntegerField(validators=[MinValueValidator(1)], verbose_name="المبلغ المدفوع")
    currency = models.CharField(max_length=10, default='IQD', verbose_name="العملة")
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS, default='zain_cash', verbose_name="طريقة الدفع")
    transaction_id = models.CharField(max_length=100, blank=True, null=True, verbose_name="رقم العملية / التوثيق")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name="حالة الدفع")
    paid_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ ووقت السداد")
    notes = models.TextField(blank=True, null=True, verbose_name="ملاحظات التسديد")

    def __str__(self):
        return f"دفعة: {self.amount} {self.currency} - {self.pharmacy.name} ({self.get_status_display()})"

# =======================================================
# 1️⃣1️⃣ جدول سجل العمليات والتدقيق (الصندوق الأسود للأمان)
# =======================================================
class AuditLog(models.Model):
    ACTION_CHOICES = [
        ('create', '➕ إنشاء / إضافة'),
        ('update', '✏️ تعديل'),
        ('delete', '🗑️ حذف'),
        ('login', '🔑 تسجيل دخول'),
        ('logout', '🚪 تسجيل خروج'),
        ('export', '📥 تصدير بيانات'),
    ]

    pharmacy = models.ForeignKey(PharmacyBranch, on_delete=models.CASCADE, related_name='audit_logs', null=True, blank=True, verbose_name="الصيدلية")
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='audit_logs', verbose_name="المستخدم")
    action = models.CharField(max_length=20, choices=ACTION_CHOICES, verbose_name="نوع الحركة")
    model_name = models.CharField(max_length=100, verbose_name="القسم / الموديل")
    object_id = models.CharField(max_length=50, blank=True, null=True, verbose_name="رقم العنصر")
    description = models.TextField(verbose_name="تفاصيل الحركة")
    ip_address = models.GenericIPAddressField(blank=True, null=True, verbose_name="عنوان ה-IP")
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ ووقت الحركة")

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        user_str = self.user.username if self.user else "نظام تلقائي"
        return f"[{self.timestamp.strftime('%Y-%m-%d %H:%M')}] {user_str} - {self.get_action_display()} في {self.model_name}"

# =======================================================
# تراخيص نسخة سطح المكتب الأوفلاين
# هذا الترخيص منفصل عن اشتراك SaaS.
# =======================================================
class DesktopLicense(models.Model):
    LICENSE_TYPE_CHOICES = [
        ('trial', 'تجريبي'),
        ('annual', 'سنوي'),
        ('lifetime', 'مدى الحياة'),
    ]

    STATUS_CHOICES = [
        ('active', 'فعال'),
        ('suspended', 'موقوف'),
        ('revoked', 'ملغى'),
    ]

    pharmacy = models.OneToOneField(
        PharmacyBranch,
        on_delete=models.CASCADE,
        related_name='desktop_license',
        verbose_name='الصيدلية',
    )

    activation_code = models.CharField(
        max_length=80,
        unique=True,
        default=generate_desktop_license_code,
        editable=False,
        verbose_name='رمز التفعيل',
    )

    license_type = models.CharField(
        max_length=20,
        choices=LICENSE_TYPE_CHOICES,
        default='lifetime',
        verbose_name='نوع الترخيص',
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='active',
        verbose_name='حالة الترخيص',
    )

    max_devices = models.PositiveSmallIntegerField(
        default=1,
        verbose_name='عدد الأجهزة المسموح بها',
    )

    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='تاريخ انتهاء الترخيص',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def is_valid(self):
        if self.status != 'active':
            return False

        if self.license_type == 'lifetime':
            return True

        return self.expires_at is not None and self.expires_at >= timezone.now()

    def __str__(self):
        return f"ترخيص سطح المكتب: {self.pharmacy.name}"


# =======================================================
# الأجهزة المفعلة لكل ترخيص
# =======================================================
class DeviceActivation(models.Model):
    license = models.ForeignKey(
        DesktopLicense,
        on_delete=models.CASCADE,
        related_name='devices',
        verbose_name='الترخيص',
    )

    device_fingerprint = models.CharField(
        max_length=128,
        verbose_name='معرف الجهاز',
    )

    device_name = models.CharField(
        max_length=120,
        blank=True,
        verbose_name='اسم الجهاز',
    )

    is_active = models.BooleanField(default=True, verbose_name='نشط')
    activated_at = models.DateTimeField(auto_now_add=True, verbose_name='تاريخ التفعيل')
    last_seen_at = models.DateTimeField(auto_now=True, verbose_name='آخر اتصال')

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['license', 'device_fingerprint'],
                name='unique_device_per_desktop_license',
            )
        ]

    def __str__(self):
        device = self.device_name or self.device_fingerprint[:12]
        return f"{self.license.pharmacy.name} - {device}"    


#موديل فواتير المذاخر
class SupplierInvoice(models.Model):
    STATUS_CHOICES = (
        ('paid', 'مدفوعة'),
        ('partial', 'مؤجلة'),
    )

    supplier = models.ForeignKey(
        PharmacySupplier,
        on_delete=models.CASCADE,
        related_name='invoices'
    )

    invoice_number = models.CharField(max_length=50)

    invoice_date = models.DateField()

    original_amount = models.IntegerField(validators=[MinValueValidator(0)])

    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default='partial'
    )

    notes = models.TextField(
        blank=True,
        null=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-invoice_date', '-id']

        constraints = [
            models.UniqueConstraint(
                fields=['supplier', 'invoice_number'],
                name='unique_invoice_per_supplier'
            )
        ]

    @property
    def total_paid(self):
        return (
            self.payments.aggregate(
                total=models.Sum('amount')
            )['total'] or 0
        )

    @property
    def total_returned(self):
        return (
            self.returns.aggregate(
                total=models.Sum('amount')
            )['total'] or 0
        )

    @property
    def total_refunded(self):
        return (
            self.refunds.aggregate(
                total=models.Sum('amount')
            )['total'] or 0
        )

    @property
    def net_amount(self):
        return self.original_amount - self.total_returned

    @property
    def remaining_amount(self):
        # ملاحظة: قد تكون النتيجة سالبة، وهذا يعني أن المذخر بات
        # مديناً للصيدلية (نتيجة دفعات أو استرجاعات تجاوزت قيمة الفاتورة).
        # لا نصفّرها هنا حتى لا تضيع هذه المعلومة.
        return self.net_amount - self.total_paid + self.total_refunded

    @property
    def is_paid(self):
        return self.remaining_amount == 0

    def update_status(self):
        """يزامن الحقل المخزن مع الرصيد الفعلي للفواتير وحركاتها."""
        new_status = 'paid' if self.remaining_amount == 0 else 'partial'
        if self.status != new_status:
            self.status = new_status
            self.save(update_fields=['status'])

    def __str__(self):
        return f"{self.supplier.name} - {self.invoice_number}"


#موديل الدفعات
class SupplierPayment(models.Model):

    invoice = models.ForeignKey(
        SupplierInvoice,
        on_delete=models.CASCADE,
        related_name='payments'
    )

    amount = models.IntegerField(validators=[MinValueValidator(1)])

    payment_date = models.DateField()

    notes = models.TextField(
        blank=True,
        null=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['payment_date', 'id']

    def __str__(self):
        return f"{self.invoice.invoice_number} - {self.amount}"


#موديل الاسترجاعات
class SupplierReturn(models.Model):

    invoice = models.ForeignKey(
        SupplierInvoice,
        on_delete=models.CASCADE,
        related_name='returns'
    )

    amount = models.IntegerField(validators=[MinValueValidator(1)])

    return_date = models.DateField()

    reason = models.CharField(
        max_length=200,
        blank=True,
        null=True
    )

    notes = models.TextField(
        blank=True,
        null=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['return_date', 'id']

    def __str__(self):
        return f"{self.invoice.invoice_number} - {self.amount}"        


#موديل استلام مبلغ من المذخر (عندما يكون المذخر مديناً للصيدلية على فاتورة معينة)
class SupplierRefund(models.Model):

    invoice = models.ForeignKey(
        SupplierInvoice,
        on_delete=models.CASCADE,
        related_name='refunds'
    )

    amount = models.IntegerField(validators=[MinValueValidator(1)])

    refund_date = models.DateField()

    notes = models.TextField(
        blank=True,
        null=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['refund_date', 'id']

    def __str__(self):
        return f"استلام من المذخر - {self.invoice.invoice_number} - {self.amount}"
