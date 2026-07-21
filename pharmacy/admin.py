from django.contrib import admin
from .models import PharmacyBranch, UserProfile, Medicine, Sale, Invoice, InvoiceItem
from .models import PharmacySupplier


# تسجيل الجداول لتظهر في لوحة التحكم
admin.site.register(PharmacyBranch)
admin.site.register(UserProfile)
admin.site.register(Medicine)
admin.site.register(Sale)
admin.site.register(Invoice)
admin.site.register(InvoiceItem)
admin.site.register(PharmacySupplier)