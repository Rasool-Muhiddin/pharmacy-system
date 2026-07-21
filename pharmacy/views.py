import json
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Count, Sum, F, Q
from django.contrib import messages
from datetime import date, datetime, timedelta
from django.http import JsonResponse
from django.db import transaction
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from .models import Medicine, Sale, MissingMedicine, Invoice, InvoiceItem, DamagedMedicine
from .iraqi_drugs import IRAQI_MEDICINES
from .models import PharmacySupplier, MissingMedicine

# 1. لوحة التحكم الرئيسية للصيدلية (تعديل العزل المتعدد للمشتركين)
@login_required
def pharmacy_dashboard(request):
    today = date.today()
    user_pharmacy = request.user.profile.pharmacy
    
    total_medicines = Medicine.objects.filter(pharmacy=user_pharmacy, is_damaged=False).count()
    
    expired_medicines = Medicine.objects.filter(
        pharmacy=user_pharmacy,
        expiry_date__lte=today, 
        is_damaged=False, 
        quantity__gt=0
    )
    
    low_stock = Medicine.objects.filter(
        pharmacy=user_pharmacy,
        quantity__lte=5, 
        is_damaged=False
    )
    
    today_sales_money = Invoice.objects.filter(
        pharmacy=user_pharmacy,
        created_at__date=today, 
        is_refunded=False
    ).aggregate(total=Sum('final_amount'))['total'] or 0.0
    
    today_sales_count = Invoice.objects.filter(
        pharmacy=user_pharmacy,
        created_at__date=today, 
        is_refunded=False
    ).count()

    context = {
        'total_medicines': total_medicines,
        'today_sales_money': "{:,}".format(float(today_sales_money)),
        'today_sales_count': today_sales_count,
        'expired_count': expired_medicines.count(),
        'low_stock_count': low_stock.count(),
        'expired_medicines': expired_medicines[:10],
        'low_stock': low_stock[:10],
        'pharmacy_name': user_pharmacy.name
    }
    return render(request, 'pharmacy/dashboard.html', context)

# 2. إدارة المخزن (مؤمنة بالكامل ومعزولة لكل صيدلية)
@login_required
def inventory(request):
    user_profile = request.user.profile
    user_pharmacy = user_profile.pharmacy

    if request.method == 'POST':
        # 🔒 فحص الأمان الحرج: منع الكاشير من الإضافة أو التحديث أو التعديل
        if not user_profile.is_pharmacy_owner:
            messages.error(request, "عذراً، لا تمتلك الصلاحية الكافية لإجراء عمليات الإضافة أو التعديل على المخزن.")
            return redirect('inventory')

        action_type = request.POST.get('action_type')

        if action_type == 'add_new':
            Medicine.objects.create(
                pharmacy=user_pharmacy,
                barcode=request.POST.get('barcode', ''), # 🌟 تمت إضافة الباركود هنا
                trade_name=request.POST.get('trade_name'),
                scientific_name=request.POST.get('scientific_name'),
                category=request.POST.get('category'),
                quantity=request.POST.get('quantity'),
                buy_price=request.POST.get('buy_price'),
                sell_price=request.POST.get('sell_price'),
                expiry_date=request.POST.get('expiry_date'),
                shelf_location=request.POST.get('shelf_location', '')
            )
        
        elif action_type == 'update_existing':
            medicine_id = request.POST.get('medicine_id')
            added_qty = int(request.POST.get('added_quantity'))
            new_expiry = request.POST.get('expiry_date')
            
            selected_med = get_object_or_404(Medicine, id=medicine_id, pharmacy=user_pharmacy)
            selected_med.quantity += added_qty
            if new_expiry:
                selected_med.expiry_date = new_expiry
            selected_med.save()

        elif action_type == 'edit_full':
            medicine_id = request.POST.get('medicine_id')
            selected_med = get_object_or_404(Medicine, id=medicine_id, pharmacy=user_pharmacy)
            
            selected_med.barcode = request.POST.get('barcode', '') # 🌟 تمت إضافة الباركود هنا
            selected_med.trade_name = request.POST.get('trade_name')
            selected_med.scientific_name = request.POST.get('scientific_name')
            selected_med.category = request.POST.get('category')
            selected_med.quantity = int(request.POST.get('quantity'))
            selected_med.buy_price = float(request.POST.get('buy_price'))
            selected_med.sell_price = float(request.POST.get('sell_price'))
            selected_med.expiry_date = request.POST.get('expiry_date')
            selected_med.shelf_location = request.POST.get('shelf_location', '')
            selected_med.save()

        return redirect('inventory')

    # --- كود العرض والفلترة (GET request) ---
    search_query = request.GET.get('search', '').strip()
    
    if search_query:
        all_medicines = Medicine.objects.filter(
            # 🌟 إضافة البحث بالباركود إلى جانب الاسم التجاري والعلمي
            Q(barcode__iexact=search_query) |
            Q(trade_name__icontains=search_query) | 
            Q(scientific_name__icontains=search_query),
            pharmacy=user_pharmacy,
            is_damaged=False
        )
    else:
        all_medicines = Medicine.objects.filter(
            pharmacy=user_pharmacy, 
            is_damaged=False
        ).order_by('expiry_date')
    
    iraqi_medicines_json = json.dumps(IRAQI_MEDICINES)
    context = {
        'medicines': all_medicines,
        'search_query': search_query,
        'iraqi_medicines': IRAQI_MEDICINES,
        'iraqi_medicines_json': iraqi_medicines_json,
        'pharmacy_name': user_pharmacy.name
    }
    return render(request, 'pharmacy/inventory.html', context)

# 3. تعديل أسعار الدواء
@login_required
def edit_prices(request, medicine_id):
    user_profile = request.user.profile
    if not user_profile.is_pharmacy_owner:
        messages.error(request, "عذراً، لا تمتلك صلاحية تعديل الأسعار.")
        return redirect('pharmacy_dashboard')
        
    user_pharmacy = user_profile.pharmacy
    medicine = get_object_or_404(Medicine, id=medicine_id, pharmacy=user_pharmacy)
    
    if request.method == 'POST':
        medicine.buy_price = request.POST.get('buy_price')
        medicine.sell_price = request.POST.get('sell_price')
        medicine.save()
        return redirect('inventory')
    
    return render(request, 'pharmacy/edit_prices.html', {'medicine': medicine})

# 4. شاشة نقطة البيع (POS)
@login_required
def pos(request):
    user_pharmacy = request.user.profile.pharmacy
    search_query = request.GET.get('search_med', '').strip()
    
    if search_query:
        medicines = Medicine.objects.filter(
            pharmacy=user_pharmacy,
            quantity__gt=0, 
            is_damaged=False
        ).filter(
            # 🌟 دعم البحث السريع بالباركود في شاشة البيع
            Q(barcode__iexact=search_query) |
            Q(trade_name__icontains=search_query) | 
            Q(scientific_name__icontains=search_query)
        )
    else:
        medicines = Medicine.objects.filter(
            pharmacy=user_pharmacy,
            quantity__gt=0, 
            is_damaged=False
        )

    if request.method == 'POST':
        medicine_ids = request.POST.getlist('medicine_ids[]')
        quantities = request.POST.getlist('quantities[]')
        discount_value_raw = request.POST.get('discount_value', '0')
        discount_type = request.POST.get('discount_type', 'amount')

        if not medicine_ids:
            messages.error(request, "لا يمكنك حفظ فاتورة فارغة! يرجى إضافة دواء أولاً.")
            return redirect('pos')

        try:
            with transaction.atomic():
                invoice = Invoice.objects.create(
                    pharmacy=user_pharmacy,
                    cashier=request.user,
                    total_amount=0.0,
                    discount=0.0,
                    final_amount=0.0
                )
                total_invoice_amount = 0

                for med_id, qty_str in zip(medicine_ids, quantities):
                    qty_sold = int(qty_str)
                    selected_med = get_object_or_404(Medicine, id=med_id, pharmacy=user_pharmacy)

                    if selected_med.quantity < qty_sold:
                        raise Exception(f"الكمية المطلوبة من {selected_med.trade_name} غير متوفرة! المتوفر: {selected_med.quantity}")

                    unit_price = selected_med.sell_price
                    total_item_price = unit_price * qty_sold
                    total_invoice_amount += total_item_price

                    InvoiceItem.objects.create(
                        invoice=invoice,
                        medicine=selected_med,
                        quantity=qty_sold,
                        unit_price=unit_price,
                        total_price=total_item_price
                    )

                    # خصم الكمية القديم
                    selected_med.quantity -= qty_sold
                    selected_med.save()

                    # 🔥🔥🔥 أضف الكود الجديد هنا مباشرةً قبل نهاية الحلقة 🔥🔥🔥
                    if selected_med.quantity == 0:
                        # التحقق أولاً منعاً للتكرار إذا كان مضافاً مسبقاً ولم يُحذف بعد
                        already_missing = MissingMedicine.objects.filter(
                            pharmacy=user_pharmacy, 
                            medicine=selected_med
                        ).exists()
                        
                        if not already_missing:
                            MissingMedicine.objects.create(
                                pharmacy=user_pharmacy,
                                medicine=selected_med,
                                medicine_name=selected_med.trade_name, # حفظ الاسم احتياطاً
                                notes="تم التحويل تلقائياً بسبب نفاد الكمية من المخزن."
                            )
                # 🛑 نهاية حلقة التكرار

                try:
                    discount_val = float(discount_value_raw)
                except ValueError:
                    discount_val = 0.0

                applied_discount = 0.0
                if discount_type == 'percent':
                    if discount_val > 100:
                        discount_val = 100.0
                    applied_discount = (total_invoice_amount * discount_val) / 100
                else:
                    if discount_val > total_invoice_amount:
                        discount_val = float(total_invoice_amount)
                    applied_discount = discount_val

                final_invoice_amount = total_invoice_amount - applied_discount

                invoice.total_amount = total_invoice_amount
                invoice.discount = applied_discount
                invoice.final_amount = final_invoice_amount
                invoice.save()

            messages.success(request, f"تم حفظ الفاتورة {invoice.invoice_number} بنجاح!")
            return redirect('pos')

        except Exception as e:
            messages.error(request, f"فشلت العملية: {str(e)}")
            return redirect('pos')

    recent_invoices = Invoice.objects.filter(
        pharmacy=user_pharmacy
    ).prefetch_related('items__medicine').order_by('-created_at')[:10]
    
    return render(request, 'pharmacy/pos.html', {
        'medicines': medicines, 
        'recent_invoices': recent_invoices, 
        'search_query': search_query,
        'pharmacy_name': user_pharmacy.name
    })

# 5. إرجاع الفاتورة
@login_required
def refund_sale(request, sale_id):
    user_pharmacy = request.user.profile.pharmacy
    invoice = get_object_or_404(Invoice, id=sale_id, pharmacy=user_pharmacy)
    
    if not invoice.is_refunded:
        with transaction.atomic():
            for item in invoice.items.all():
                medicine = item.medicine
                medicine.quantity += item.quantity
                medicine.save()
            
            invoice.is_refunded = True
            invoice.save()
            messages.success(request, f"تم إرجاع الفاتورة رقم {invoice.id} بنجاح وإعادة الأدوية للمخزن.")
    else:
        messages.warning(request, "هذه الفاتورة تم إرجاعها مسبقاً!")
        
    return redirect('pos')

# 6. النواقص
# 6. النواقص

@login_required

@login_required
def missing_medicines_view(request):
    user_pharmacy = request.user.profile.pharmacy

    if request.method == 'POST':
        action = request.POST.get('action') # سنفرق بين الإضافة الجديدة وتحديث مذخر لدواء موجود

        # 🛑 الحالة الأولى: إضافة دواء ناقص جديد يدوياً
        if action == 'add_new_missing':
            name = request.POST.get('medicine_name')
            notes = request.POST.get('notes', '')
            supplier_id = request.POST.get('supplier_id') # المذخر المختار من القائمة
            new_supplier_name = request.POST.get('new_supplier_name', '').strip()
            new_supplier_phone = request.POST.get('new_supplier_phone', '').strip()

            if name:
                selected_supplier = None
                
                # إذا كتب الصيدلي اسم مذخر جديد
                if new_supplier_name:
                    # جلب المذخر إذا كان موجوداً مسبقاً أو إنشائه لمنع التكرار
                    selected_supplier, created = PharmacySupplier.objects.get_or_create(
                        pharmacy=user_pharmacy,
                        name=new_supplier_name,
                        defaults={'phone': new_supplier_phone}
                    )
                # إذا اختار مذخراً جاهزاً من القائمة المنسدلة
                elif supplier_id and supplier_id != 'new':
                    selected_supplier = get_object_or_404(PharmacySupplier, id=supplier_id, pharmacy=user_pharmacy)

                # إنشاء سجل النواقص
                MissingMedicine.objects.create(
                    pharmacy=user_pharmacy,
                    medicine_name=name,
                    supplier=selected_supplier,
                    notes=notes
                )
                messages.success(request, f"تم إضافة دواء ({name}) إلى قائمة النواقص.")
                return redirect('missing_medicines')

        # 🛑 الحالة الثانية: تحديد أو تحديث المذخر لدواء (مثل الأدوية المتحولة تلقائياً)
        elif action == 'update_supplier':
            missing_item_id = request.POST.get('missing_item_id')
            supplier_id = request.POST.get('supplier_id')
            new_supplier_name = request.POST.get('new_supplier_name', '').strip()
            new_supplier_phone = request.POST.get('new_supplier_phone', '').strip()

            missing_item = get_object_or_404(MissingMedicine, id=missing_item_id, pharmacy=user_pharmacy)
            selected_supplier = None

            if new_supplier_name:
                selected_supplier, created = PharmacySupplier.objects.get_or_create(
                    pharmacy=user_pharmacy,
                    name=new_supplier_name,
                    defaults={'phone': new_supplier_phone}
                )
            elif supplier_id and supplier_id != 'new':
                selected_supplier = get_object_or_404(PharmacySupplier, id=supplier_id, pharmacy=user_pharmacy)

            missing_item.supplier = selected_supplier
            missing_item.save()
            messages.success(request, "تم تحديث بيانات المذخر للدواء الناقص بنجاح.")
            return redirect('missing_medicines')

    # جلب البيانات للعرض (GET)
    missing_list = MissingMedicine.objects.filter(pharmacy=user_pharmacy).select_related('supplier', 'medicine').order_by('-requested_at')
    suppliers_list = PharmacySupplier.objects.filter(pharmacy=user_pharmacy).order_by('name')

    context = {
        'missing_list': missing_list, 
        'suppliers_list': suppliers_list,
        'pharmacy_name': user_pharmacy.name
    }
    return render(request, 'pharmacy/missing_medicines.html', context)

@login_required
def delete_missing_medicine(request, pk):
    user_profile = request.user.profile
    if not user_profile.is_pharmacy_owner:
        messages.error(request, "عذراً، لا تمتلك الصلاحية لشطب النواقص من القائمة.")
        return redirect('missing_medicines')
        
    user_pharmacy = user_profile.pharmacy
    item = get_object_or_404(MissingMedicine, id=pk, pharmacy=user_pharmacy)
    item.delete()
    return redirect('missing_medicines')
    
# 7. الإتلاف
@login_required
def damage_medicine(request, medicine_id):
    if request.method == "POST":
        user_profile = request.user.profile
        if not user_profile.is_pharmacy_owner:
            messages.error(request, "عذراً، لا تمتلك الصلاحية لنقل الأدوية للتوالف.")
            return redirect('inventory')
            
        user_pharmacy = user_profile.pharmacy
        medicine = get_object_or_404(Medicine, id=medicine_id, pharmacy=user_pharmacy)
        
        try:
            qty_to_damage = int(request.POST.get('quantity_damaged', 0))
            damage_reason = request.POST.get('reason', 'other')
            damage_notes = request.POST.get('notes', '').strip()
        except ValueError:
            messages.error(request, "الرجاء إدخال كمية صحيحة.")
            return redirect('inventory')

        if qty_to_damage <= 0:
            messages.error(request, "يجب أن تكون الكمية التالفة أكبر من الصفر.")
            return redirect('inventory')
            
        if qty_to_damage > medicine.quantity:
            messages.error(request, f"الكمية المدخلة ({qty_to_damage}) أكبر من المتوفر في المخزن ({medicine.quantity})!")
            return redirect('inventory')

        try:
            with transaction.atomic():
                medicine.quantity -= qty_to_damage
                medicine.save()

                DamagedMedicine.objects.create(
                    pharmacy=user_pharmacy,
                    medicine=medicine,
                    quantity_damaged=qty_to_damage,
                    reason=damage_reason,
                    notes=damage_notes
                )
                
            messages.success(request, f"تم نقل ({qty_to_damage} علبة) من دواء ({medicine.trade_name}) إلى قائمة التوالف بنجاح.")
        except Exception as e:
            messages.error(request, f"حدث خطأ أثناء معالجة الطلب: {str(e)}")
            
    return redirect('inventory')

# 8. سجل الفواتير والمبيعات
@login_required
def sales_history(request):
    user_profile = request.user.profile
    user_pharmacy = user_profile.pharmacy
    search_query = request.GET.get('search_query', '').strip()
    
    # 1️⃣ جعلنا المتغير الأساسي باسم invoices وتفعيل التحميل المسبق لمنع ثقل السيرفر
    invoices = Invoice.objects.filter(
        pharmacy=user_pharmacy
    ).select_related('cashier').prefetch_related('items__medicine')

    if search_query:
        search_filter = Q()
        
        # 1️⃣ الحالة الأولى: إذا كتب المستخدم رقم الفاتورة كاملاً (مثل INV-5)
        if search_query.upper().startswith('INV'):
            search_filter |= Q(invoice_number__iexact=search_query)
            
        # 2️⃣ الحالة الثانية: إذا كتب المستخدم رقماً مجرداً فقط (مثل 5 أو 12)
        elif search_query.isdigit():
            search_filter |= Q(id=int(search_query))
            search_filter |= Q(invoice_number__endswith=f"-{search_query}")
            
        # 3️⃣ الحالة الثالثة: إذا كتب صيغة تاريخ تحتوي على فواصل (مثل 2026-05)
        elif '-' in search_query or '/' in search_query:
            search_filter |= Q(created_at__icontains=search_query)
            
        # 4️⃣ الحالة الرابعة: إذا كتب نصاً عادياً (اسم دواء، باركود، أو اسم الكاشير)
        else:
            search_filter |= Q(items__medicine__barcode__iexact=search_query)
            search_filter |= Q(items__medicine__trade_name__icontains=search_query)
            search_filter |= Q(items__medicine__scientific_name__icontains=search_query)
            search_filter |= Q(cashier__username__icontains=search_query)

        # فلترة الاستعلام الأساسي مباشرةً مع منع التكرار (distinct)
        invoices = invoices.filter(search_filter).distinct()

    # 2️⃣ ترتيب النتائج النهائي دائماً من الأحدث إلى الأقدم
    invoices = invoices.order_by('-created_at')

    cashier_summary = []
    if user_profile.is_pharmacy_owner:
        today = timezone.now().date()
        pharmacy_users = User.objects.filter(profile__pharmacy=user_pharmacy)
        
        for u in pharmacy_users:
            today_invoices = Invoice.objects.filter(
                pharmacy=user_pharmacy,
                cashier=u,
                created_at__date=today
            ).order_by('-created_at')
            
            total_sales = today_invoices.aggregate(Sum('final_amount'))['final_amount__sum'] or 0.0
            
            cashier_summary.append({
                'username': u.username,
                'total_sales': total_sales,
                'bill_count': today_invoices.count(),
                'invoices_list': today_invoices
            })

    return render(request, 'pharmacy/sales_history.html', {
        'invoices': invoices,
        'search_query': search_query,
        'pharmacy_name': user_pharmacy.name,
        'is_owner': user_profile.is_pharmacy_owner,
        'cashier_summary': cashier_summary
    })

# 9. التقارير المالية
@login_required
def sales_reports(request):
    user_profile = request.user.profile
    if not user_profile.is_pharmacy_owner:
        messages.error(request, "عذراً، هذه الصفحة مخصصة للإدارة فقط.")
        return redirect('pharmacy_dashboard')
    
    user_pharmacy = user_profile.pharmacy
    
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')

    if start_date_str and end_date_str:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d') + timedelta(days=1) - timedelta(seconds=1)
    else:
        end_date = timezone.now()
        start_date = end_date - timedelta(days=30)
        start_date_str = start_date.strftime('%Y-%m-%d')
        end_date_str = end_date.strftime('%Y-%m-%d')

    invoices = Invoice.objects.filter(
        pharmacy=user_pharmacy,
        created_at__range=(start_date, end_date),
        is_refunded=False
    ).prefetch_related('items__medicine').order_by('-created_at')

    total_sales = invoices.aggregate(Sum('final_amount'))['final_amount__sum'] or 0.0
    total_invoices_count = invoices.count()
    total_discounts_given = invoices.aggregate(Sum('discount'))['discount__sum'] or 0.0

    today = timezone.now().date()
    expired_medicines = Medicine.objects.filter(
        pharmacy=user_pharmacy,
        expiry_date__lt=today,
        quantity__gt=0,
        is_damaged=False
    )
    total_expired_losses = sum(med.quantity * med.buy_price for med in expired_medicines)

    damaged_losses_query = DamagedMedicine.objects.filter(
        medicine__pharmacy=user_pharmacy
    ).annotate(
        loss_amount=F('quantity_damaged') * F('medicine__buy_price')
    ).aggregate(total_loss=Sum('loss_amount'))
    
    total_damaged_losses = damaged_losses_query['total_loss'] or 0
    total_combined_losses = total_expired_losses + total_damaged_losses

    top_selling_items = InvoiceItem.objects.filter(
        invoice__pharmacy=user_pharmacy,
        invoice__created_at__range=(start_date, end_date),
        invoice__is_refunded=False
    ).values(
        'medicine__trade_name', 'medicine__scientific_name', 'medicine__category'
    ).annotate(
        total_qty=Sum('quantity'),
        total_revenue=Sum('total_price')
    ).order_by('-total_qty')[:5]

    sold_medicine_ids = InvoiceItem.objects.filter(
        invoice__pharmacy=user_pharmacy,
        invoice__created_at__range=(start_date, end_date),
        invoice__is_refunded=False
    ).values_list('medicine_id', flat=True).distinct()

    stagnant_medicines = Medicine.objects.filter(
        pharmacy=user_pharmacy,
        is_damaged=False,
        quantity__gt=0
    ).exclude(id__in=sold_medicine_ids)[:10]

    context = {
        'invoices': invoices,
        'start_date': start_date_str,
        'end_date': end_date_str,
        'total_sales': int(total_sales),
        'total_discounts_given': int(total_discounts_given),
        'total_invoices_count': total_invoices_count,
        'total_damage_losses': int(total_combined_losses), 
        'top_selling_items': top_selling_items,
        'stagnant_medicines': stagnant_medicines,
        'pharmacy_name': user_pharmacy.name
    }
    return render(request, 'pharmacy/reports.html', context)

# 10. التوالف
@login_required
def damaged_medicines_list(request):
    user_profile = request.user.profile
    if not user_profile.is_pharmacy_owner:
        messages.error(request, "عذراً، هذه الصفحة مخصصة للمدير وصاحب الصيدلية فقط.")
        return redirect('pharmacy_dashboard')
        
    user_pharmacy = user_profile.pharmacy
    damaged_list = DamagedMedicine.objects.filter(
        pharmacy=user_pharmacy
    ).select_related('medicine').order_by('-damaged_at')
    
    total_losses = sum(item.quantity_damaged * item.medicine.buy_price for item in damaged_list)
    
    return render(request, 'pharmacy/damaged_medicines.html', {
        'damaged_list': damaged_list,
        'total_losses': total_losses,
        'pharmacy_name': user_pharmacy.name
    })

# تسجيل الدخول والخروج
def login_view(request):
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(username=username, password=password)
            if user is not None:
                login(request, user)
                return redirect('pharmacy_dashboard')
    else:
        form = AuthenticationForm()
    return render(request, 'pharmacy/login.html', {'form': form})

def logout_view(request):
    logout(request)
    return redirect('login')

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'pharmacy_dashboard'
LOGOUT_REDIRECT_URL = 'login'

def landing_page(request):
    return render(request, 'pharmacy/landing.html')