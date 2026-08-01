from django.contrib import admin
from .models import (
    PharmacyBranch, UserProfile, Medicine, Sale,
    Invoice, InvoiceItem, PharmacySupplier, MissingMedicine,
    DamagedMedicine, Subscription, Payment, AuditLog,
    DesktopLicense, DeviceActivation,
)

# =======================================================
# 1️⃣ إدارة الصيدليات والمستخدمين
# =======================================================
@admin.register(PharmacyBranch)
class PharmacyBranchAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active', 'created_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('name',)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'pharmacy', 'is_pharmacy_owner')
    list_filter = ('is_pharmacy_owner', 'pharmacy')
    search_fields = ('user__username', 'pharmacy__name')


# =======================================================
# 2️⃣ إدارة الأدوية والمخزون
# =======================================================
@admin.register(Medicine)
class MedicineAdmin(admin.ModelAdmin):
    list_display = ('trade_name', 'scientific_name', 'pharmacy', 'category', 'quantity', 'sell_price', 'expiry_date', 'barcode')
    list_filter = ('pharmacy', 'category', 'is_damaged')
    search_fields = ('trade_name', 'scientific_name', 'barcode')
    ordering = ('trade_name',)

    list_per_page = 50


@admin.register(DamagedMedicine)
class DamagedMedicineAdmin(admin.ModelAdmin):
    list_display = ('medicine', 'pharmacy', 'quantity_damaged', 'reason', 'damaged_at')
    list_filter = ('pharmacy', 'reason', 'damaged_at')
    search_fields = ('medicine__trade_name',)

    list_per_page = 50

# =======================================================
# 3️⃣ إدارة المذاخر والنواقص
# =======================================================
@admin.register(PharmacySupplier)
class PharmacySupplierAdmin(admin.ModelAdmin):
    list_display = ('name', 'pharmacy', 'phone', 'created_at')
    list_filter = ('pharmacy',)
    search_fields = ('name', 'phone')

    list_per_page = 50


@admin.register(MissingMedicine)
class MissingMedicineAdmin(admin.ModelAdmin):
    list_display = ('medicine_name', 'pharmacy', 'supplier', 'requested_at')
    list_filter = ('pharmacy', 'supplier', 'requested_at')
    search_fields = ('medicine_name', 'notes')

    list_per_page = 50

# =======================================================
# 4️⃣ إدارة المبيعات والفواتير
# =======================================================
@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ('medicine', 'pharmacy', 'quantity_sold', 'total_price', 'cashier', 'sold_at', 'is_refunded')
    list_filter = ('pharmacy', 'is_refunded', 'sold_at')
    search_fields = ('medicine__trade_name', 'cashier__username')

    list_per_page = 50

# عرض تفاصيل عناصر الفاتورة مدمجة داخل صفحة الفاتورة الرئيسية
class InvoiceItemInline(admin.TabularInline):
    model = InvoiceItem
    extra = 0
    readonly_fields = ('medicine', 'quantity', 'unit_price', 'total_price')

    


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('invoice_number', 'pharmacy', 'cashier', 'total_amount', 'discount', 'final_amount', 'created_at', 'is_refunded')
    list_filter = ('pharmacy', 'is_refunded', 'created_at')
    search_fields = ('invoice_number', 'cashier__username')
    inlines = [InvoiceItemInline]

    list_per_page = 50

@admin.register(InvoiceItem)
class InvoiceItemAdmin(admin.ModelAdmin):
    list_display = ('invoice', 'medicine', 'quantity', 'unit_price', 'total_price')
    search_fields = ('invoice__invoice_number', 'medicine__trade_name')


# =======================================================
# 5️⃣ إدارة الاشتراكات، المدفوعات، وسجل التدقيق
# =======================================================
@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('pharmacy', 'plan_type', 'status', 'start_date', 'end_date', 'is_valid')
    list_filter = ('plan_type', 'status', 'is_auto_renew')
    search_fields = ('pharmacy__name',)
    ordering = ('-end_date',)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('pharmacy', 'amount', 'currency', 'payment_method', 'status', 'paid_at')
    list_filter = ('status', 'payment_method', 'currency')
    search_fields = ('pharmacy__name', 'transaction_id')
    ordering = ('-paid_at',)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'user', 'pharmacy', 'action', 'model_name', 'ip_address')
    list_filter = ('action', 'model_name', 'timestamp')
    search_fields = ('user__username', 'pharmacy__name', 'description')
    
    # حماية سجل التدقيق من التعديل أو الحذف
    readonly_fields = ('pharmacy', 'user', 'action', 'model_name', 'object_id', 'description', 'ip_address', 'timestamp')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

# =======================================================
# إدارة تراخيص نسخة سطح المكتب والأجهزة المفعلة
# =======================================================
class DeviceActivationInline(admin.TabularInline):
    model = DeviceActivation
    extra = 0
    fields = (
        'device_name',
        'device_fingerprint',
        'is_active',
        'activated_at',
        'last_seen_at',
    )
    readonly_fields = (
        'device_fingerprint',
        'activated_at',
        'last_seen_at',
    )


@admin.register(DesktopLicense)
class DesktopLicenseAdmin(admin.ModelAdmin):
    list_display = (
        'pharmacy',
        'activation_code',
        'license_type',
        'status',
        'max_devices',
        'active_devices_count',
        'expires_at',
        'is_valid',
    )

    list_filter = ('license_type', 'status')
    search_fields = ('pharmacy__name', 'activation_code')
    ordering = ('-created_at',)

    readonly_fields = (
        'activation_code',
        'created_at',
        'updated_at',
        'active_devices_count',
        'is_valid',
    )

    fields = (
        'pharmacy',
        'activation_code',
        'license_type',
        'status',
        'max_devices',
        'expires_at',
        'active_devices_count',
        'is_valid',
        'created_at',
        'updated_at',
    )

    inlines = [DeviceActivationInline]

    actions = ('activate_licenses', 'suspend_licenses')

    @admin.display(description='الأجهزة المفعلة')
    def active_devices_count(self, obj):
        if not obj:
            return 0
        return obj.devices.filter(is_active=True).count()

    @admin.action(description='تفعيل التراخيص المحددة')
    def activate_licenses(self, request, queryset):
        queryset.update(status='active')

    @admin.action(description='إيقاف التراخيص المحددة')
    def suspend_licenses(self, request, queryset):
        queryset.update(status='suspended')


@admin.register(DeviceActivation)
class DeviceActivationAdmin(admin.ModelAdmin):
    list_display = (
        'license',
        'device_name',
        'short_fingerprint',
        'is_active',
        'activated_at',
        'last_seen_at',
    )

    list_filter = ('is_active', 'activated_at')
    search_fields = (
        'license__pharmacy__name',
        'device_name',
        'device_fingerprint',
    )

    readonly_fields = (
        'license',
        'device_fingerprint',
        'activated_at',
        'last_seen_at',
    )

    @admin.display(description='معرف الجهاز')
    def short_fingerprint(self, obj):
        return obj.device_fingerprint[:20]    