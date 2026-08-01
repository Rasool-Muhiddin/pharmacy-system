from django.urls import path
from . import views

urlpatterns = [
    path('dashboard/', views.pharmacy_dashboard, name='pharmacy_dashboard'),
    path('inventory/', views.inventory, name='inventory'),
    path('pos/', views.pos, name='pos'),
    path('edit-prices/<int:medicine_id>/', views.edit_prices, name='edit_prices'),
    path('refund-sale/<int:sale_id>/', views.refund_sale, name='refund_sale'),
    path('missing-medicines/', views.missing_medicines_view, name='missing_medicines'),
    path('missing-medicines/delete/<int:pk>/', views.delete_missing_medicine, name='delete_missing_medicine'),
    path('medicine/damage/<int:medicine_id>/', views.damage_medicine, name='damage_medicine'),
    path('sales-history/', views.sales_history, name='sales_history'),
    path('reports/', views.sales_reports, name='sales_reports'),
    path('login/', views.login_view, name='login'),
    path('api/desktop/activate/', views.desktop_activate, name='desktop_activate'),
    path('api/desktop/login/', views.desktop_login, name='desktop_login'),
    path('logout/', views.logout_view, name='logout'),
    path('damaged-medicines/', views.damaged_medicines_list, name='damaged_medicines'),
    path('', views.landing_page, name='landing_page'),
]
