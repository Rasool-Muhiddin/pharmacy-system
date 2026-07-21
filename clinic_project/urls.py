from django.contrib import admin
from django.urls import path, include  # تأكد من إضافة include هنا
from pharmacy import views as pharmacy_views

urlpatterns = [
    path('admin/', admin.site.urls),
 
    path('pharmacy/', include('pharmacy.urls')),

    path('', pharmacy_views.landing_page, name='landing_page'),
]