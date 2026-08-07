from django.urls import path
from . import views

urlpatterns = [
    path('dashboard/', views.pharmacy_dashboard, name='pharmacy_dashboard'),
    path('inventory/', views.inventory, name='inventory'),
    path('pos/', views.pos, name='pos'),
    path('edit-prices/<int:medicine_id>/', views.edit_prices, name='edit_prices'),
    path('refund-sale/<int:sale_id>/', views.refund_sale, name='refund_sale'),
    path('missing-medicines/', views.missing_medicines_view, name='missing_medicines'),
    path('missing-medicines/add-supplier/',views.add_supplier,name='add_supplier'),
    path('missing-medicines/edit-supplier/<int:pk>/',views.edit_supplier,name='edit_supplier'),
    path('missing-medicines/delete-supplier/<int:pk>/',views.delete_supplier,name='delete_supplier'),
    path('missing-medicines/add-invoice/<int:supplier_id>/', views.add_invoice, name='add_invoice'),
    path('missing-medicines/add-payment/<int:invoice_id>/', views.add_payment, name='add_payment'),
    path('missing-medicines/add-return/<int:invoice_id>/', views.add_return, name='add_return'),
    path('missing-medicines/settle-debt/<int:invoice_id>/', views.settle_supplier_debt, name='settle_supplier_debt'),
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