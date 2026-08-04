import json
from django.shortcuts import render, redirect, get_object_or_404
from decimal import Decimal
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
from django.core.exceptions import ObjectDoesNotExist
from .models import (
    Medicine, Sale, Invoice, InvoiceItem,
    DamagedMedicine, PharmacySupplier, DesktopLicense, DeviceActivation, UserProfile,
    SupplierInvoice,  SupplierPayment, SupplierReturn,
)
from .iraqi_drugs import IRAQI_MEDICINES
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.db.models.functions import Coalesce

# 1. لوحة التحكم الرئيسية للصيدلية
@login_required
def pharmacy_dashboard(request):
    try:
        user_pharmacy = request.user.profile.pharmacy
    except ObjectDoesNotExist:
        messages.error(request, "حسابك غير مرتبط بصيدلية مفعلة. يرجى مراجعة الدعم الفني.")
        return redirect('login')

    today = date.today()
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


# 2. إدارة المخزن (محصنة بالكامل ضد الأخطاء الإدخالية)
@login_required
def inventory(request):
    try:
        user_profile = request.user.profile
        user_pharmacy = user_profile.pharmacy
    except ObjectDoesNotExist:
        messages.error(request, "حسابك غير مرتبط بصيدلية.")
        return redirect('login')

    if request.method == 'POST':
        if not user_profile.is_pharmacy_owner:
            messages.error(request, "عذراً، لا تمتلك الصلاحية الكافية لإجراء عمليات الإضافة أو التعديل.")
            return redirect('inventory')

        action_type = request.POST.get('action_type')

        raw_barcode = request.POST.get('barcode', '').strip()
        barcode_val = raw_barcode if raw_barcode else None

        # 🛡️ فحص أمان التاريخ
        expiry_date_input = request.POST.get('expiry_date')
        if expiry_date_input:
            try:
                exp_year = datetime.strptime(expiry_date_input, '%Y-%m-%d').year
                if exp_year < 2000 or exp_year > 2099:
                    messages.error(request, "سنة الصلاحية غير منطقية! يرجى إدخال تاريخ صحيح.")
                    return redirect('inventory')
            except ValueError:
                messages.error(request, "صيغة التاريخ غير صحيحة.")
                return redirect('inventory')

        try:
            if action_type == 'add_new':
                quantity = int(request.POST.get('quantity', 0))
                buy_price = float(request.POST.get('buy_price', 0))
                sell_price = float(request.POST.get('sell_price', 0))

                if quantity < 0 or buy_price < 0 or sell_price < 0:
                    messages.error(request, "لا يمكن إدخال قيم بالسالب للكميات أو الأسعار!")
                    return redirect('inventory')

                Medicine.objects.create(
                    pharmacy=user_pharmacy,
                    barcode=barcode_val,
                    trade_name=request.POST.get('trade_name'),
                    scientific_name=request.POST.get('scientific_name'),
                    category=request.POST.get('category'),
                    quantity=quantity,
                    buy_price=buy_price,
                    sell_price=sell_price,
                    expiry_date=expiry_date_input,
                    shelf_location=request.POST.get('shelf_location', '')
                )
                messages.success(request, "تم إضافة الدواء للمخزن بنجاح.")

            elif action_type == 'update_existing':
                medicine_id = request.POST.get('medicine_id')
                added_qty = int(request.POST.get('added_quantity', 0))
                
                if added_qty <= 0:
                    messages.error(request, "يرجى إدخال كمية مضافة أكبر من الصفر.")
                    return redirect('inventory')

                selected_med = get_object_or_404(Medicine, id=medicine_id, pharmacy=user_pharmacy)
                selected_med.quantity += added_qty
                if expiry_date_input:
                    selected_med.expiry_date = expiry_date_input
                selected_med.save()
                messages.success(request, f"تم تحديث كمية {selected_med.trade_name} بنجاح.")

            elif action_type == 'edit_full':
                medicine_id = request.POST.get('medicine_id')
                selected_med = get_object_or_404(Medicine, id=medicine_id, pharmacy=user_pharmacy)
                
                quantity = int(request.POST.get('quantity', 0))
                buy_price = float(request.POST.get('buy_price', 0))
                sell_price = float(request.POST.get('sell_price', 0))

                if quantity < 0 or buy_price < 0 or sell_price < 0:
                    messages.error(request, "لا يمكن قبول قيم بالسالب!")
                    return redirect('inventory')

                selected_med.barcode = barcode_val
                selected_med.trade_name = request.POST.get('trade_name')
                selected_med.scientific_name = request.POST.get('scientific_name')
                selected_med.category = request.POST.get('category')
                selected_med.quantity = quantity
                selected_med.buy_price = buy_price
                selected_med.sell_price = sell_price
                selected_med.expiry_date = expiry_date_input
                selected_med.shelf_location = request.POST.get('shelf_location', '')
                selected_med.save()
                messages.success(request, "تم تعديل بيانات الدواء بنجاح.")

        except (ValueError, TypeError):
            messages.error(request, "حدث خطأ في المدخلات الرقمية! يرجى التأكد من كتابة أرقام صحيحة للأسعار والكميات.")
            return redirect('inventory')
        except Exception as e:
            messages.error(request, f"تعذر تنفيذ العملية: {str(e)}")
            return redirect('inventory')

        return redirect('inventory')

    # GET Request
    search_query = request.GET.get('search', '').strip()
    if search_query:
        all_medicines = Medicine.objects.filter(
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
        try:
            buy_price = float(request.POST.get('buy_price', 0))
            sell_price = float(request.POST.get('sell_price', 0))

            if buy_price < 0 or sell_price < 0:
                messages.error(request, "الأسعار لا يمكن أن تكون بالسالب!")
                return render(request, 'pharmacy/edit_prices.html', {'medicine': medicine})

            medicine.buy_price = buy_price
            medicine.sell_price = sell_price
            medicine.save()
            messages.success(request, "تم تعديل الأسعار بنجاح.")
            return redirect('inventory')
        except (ValueError, TypeError):
            messages.error(request, "يرجى إدخال أرقام صحيحة للأسعار.")
            return render(request, 'pharmacy/edit_prices.html', {'medicine': medicine})
    
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
                    if qty_sold <= 0:
                        raise Exception("كمية البيع يجب أن تكون أكبر من الصفر!")

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

                    selected_med.quantity -= qty_sold
                    selected_med.save()

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
                if medicine:
                    medicine.quantity += item.quantity
                    medicine.save()
            
            invoice.is_refunded = True
            invoice.save()
            messages.success(request, f"تم إرجاع الفاتورة بنجاح وإعادة الأدوية للمخزن.")
    else:
        messages.warning(request, "هذه الفاتورة تم إرجاعها مسبقاً!")
        
    return redirect('pos')


# =======================================================
# 6. إدارة المذاخر والفواتير (النواقص سابقاً)
# =======================================================

@login_required
def missing_medicines_view(request):
    search = request.GET.get("search", "").strip()
    user_profile = request.user.profile
    user_pharmacy = user_profile.pharmacy

    suppliers = (
        PharmacySupplier.objects
        .filter(pharmacy=user_pharmacy)
        .prefetch_related(
            'invoices',
            'invoices__payments',
            'invoices__returns'
        )
    )
    if search:
        suppliers = suppliers.filter(name__icontains=search)
        
    suppliers = suppliers.annotate(
        invoices_count=Count("invoices", distinct=True)
    )
    
    total_debt = 0
    top_supplier = None
    top_supplier_total = 0
    supplier_data = []
    
    for supplier in suppliers:
        invoices = list(supplier.invoices.all())
        total_purchase = sum(invoice.net_amount for invoice in invoices)
        supplier_debt = sum(invoice.remaining_amount for invoice in invoices)
        
        supplier_data.append({
            "supplier": supplier,
            "invoices": invoices,
            "total_purchase": total_purchase,
            "total_debt": supplier_debt,
            "invoice_count": supplier.invoices_count,
        })
        
        total_debt += supplier_debt
        if total_purchase > top_supplier_total:
            top_supplier_total = total_purchase
            top_supplier = supplier

    context = {
        "supplier_data": supplier_data,
        "total_debt": total_debt,
        "top_supplier": top_supplier,
        "top_supplier_total": top_supplier_total,
        "search": search,
        "today": timezone.now().date(),
    }
    return render(request, "pharmacy/missing_medicines.html", context)



# إضافة مذخر
@login_required
def add_supplier(request):
    if request.method != "POST":
        return redirect("missing_medicines")
        
    user_profile = request.user.profile
    if not user_profile.is_pharmacy_owner:
        messages.error(request, "ليس لديك صلاحية لإضافة مذخر.")
        return redirect("missing_medicines")
        
    pharmacy = user_profile.pharmacy
    name = request.POST.get("name", "").strip()
    phone = request.POST.get("phone", "").strip()

    if not name:
        messages.error(request, "يرجى إدخال اسم المذخر.")
        return redirect("missing_medicines")
        
    if PharmacySupplier.objects.filter(pharmacy=pharmacy, name=name).exists():
        messages.warning(request, "يوجد مذخر بنفس الاسم.")
        return redirect("missing_medicines")
        
    PharmacySupplier.objects.create(
        pharmacy=pharmacy,
        name=name,
        phone=phone
    )
    messages.success(request, "تمت إضافة المذخر بنجاح.")
    return redirect("missing_medicines")


# تعديل مذخر
@login_required
def edit_supplier(request, pk):
    if request.method != "POST":
        return redirect("missing_medicines")

    user_profile = request.user.profile
    if not user_profile.is_pharmacy_owner:
        messages.error(request, "ليس لديك صلاحية.")
        return redirect("missing_medicines")

    pharmacy = user_profile.pharmacy
    supplier = get_object_or_404(PharmacySupplier, pk=pk, pharmacy=pharmacy)

    name = request.POST.get("name", "").strip()
    phone = request.POST.get("phone", "").strip()

    if not name:
        messages.error(request, "اسم المذخر مطلوب.")
        return redirect("missing_medicines")

    if PharmacySupplier.objects.filter(pharmacy=pharmacy, name=name).exclude(pk=supplier.pk).exists():
        messages.warning(request, "يوجد مذخر آخر بنفس الاسم.")
        return redirect("missing_medicines")

    supplier.name = name
    supplier.phone = phone
    supplier.save()

    messages.success(request, "تم تحديث بيانات المذخر.")
    return redirect("missing_medicines")


# حذف مذخر
@login_required
def delete_supplier(request, pk):
    user_profile = request.user.profile
    if not user_profile.is_pharmacy_owner:
        messages.error(request, "ليس لديك صلاحية.")
        return redirect("missing_medicines")

    pharmacy = user_profile.pharmacy
    supplier = get_object_or_404(PharmacySupplier, pk=pk, pharmacy=pharmacy)

    if supplier.invoices.exists():
        messages.warning(request, "لا يمكن حذف مذخر يحتوي على فواتير.")
        return redirect("missing_medicines")

    supplier.delete()
    messages.success(request, "تم حذف المذخر.")
    return redirect("missing_medicines")


# إضافة فاتورة للمذخر
@login_required
def add_invoice(request, supplier_id):
    if request.method != "POST":
        return redirect("missing_medicines")

    user_profile = request.user.profile
    if not user_profile.is_pharmacy_owner:
        messages.error(request, "ليس لديك صلاحية لإضافة فاتورة.")
        return redirect("missing_medicines")

    supplier = get_object_or_404(
        PharmacySupplier,
        id=supplier_id,
        pharmacy=user_profile.pharmacy
    )

    invoice_number = request.POST.get("invoice_number", "").strip()
    invoice_date = request.POST.get("invoice_date") or timezone.now().date()
    original_amount_raw = request.POST.get("original_amount", "0").strip()
    payment_type = request.POST.get("payment_type")
    notes = request.POST.get("notes", "").strip()
    first_payment_raw = request.POST.get("first_payment", "0").strip()

    if not invoice_number:
        messages.error(request, "رقم الفاتورة مطلوب.")
        return redirect("missing_medicines")

    if SupplierInvoice.objects.filter(supplier=supplier, invoice_number=invoice_number).exists():
        messages.warning(request, "رقم الفاتورة مستخدم مسبقاً لهذا المذخر.")
        return redirect("missing_medicines")

    try:
        original_amount = Decimal(original_amount_raw or "0")
    except Exception:
        messages.error(request, "مبلغ الفاتورة غير صحيح.")
        return redirect("missing_medicines")

    with transaction.atomic():
        invoice = SupplierInvoice.objects.create(
            supplier=supplier,
            invoice_number=invoice_number,
            invoice_date=invoice_date,
            original_amount=original_amount,
            status="partial",
            notes=notes,
        )

        if payment_type == "paid":
            SupplierPayment.objects.create(
                invoice=invoice,
                amount=invoice.original_amount,
                payment_date=invoice.invoice_date,
                notes="تم الدفع بالكامل عند إنشاء الفاتورة."
            )
        elif payment_type == "partial":
            try:
                first_payment = Decimal(first_payment_raw or "0")
            except Exception:
                first_payment = Decimal("0")

            if first_payment > invoice.original_amount:
                transaction.set_rollback(True)
                messages.error(request, "الدفعة الأولى لا يمكن أن تكون أكبر من مبلغ الفاتورة.")
                return redirect("missing_medicines")

            if first_payment > 0:
                SupplierPayment.objects.create(
                    invoice=invoice,
                    amount=first_payment,
                    payment_date=invoice.invoice_date,
                    notes="الدفعة الأولى."
                )

    messages.success(request, "تمت إضافة الفاتورة بنجاح.")
    return redirect("missing_medicines")


# إضافة دفعة مالية لفاتورة
@login_required
def add_payment(request, invoice_id):
    if request.method != "POST":
        return redirect("missing_medicines")

    user_profile = request.user.profile
    if not user_profile.is_pharmacy_owner:
        messages.error(request, "ليس لديك صلاحية لتسجيل الدفعات.")
        return redirect("missing_medicines")

    invoice = get_object_or_404(
        SupplierInvoice,
        id=invoice_id,
        supplier__pharmacy=user_profile.pharmacy
    )

    amount_raw = request.POST.get("amount", "0").strip()
    payment_date = request.POST.get("payment_date") or timezone.now().date()
    notes = request.POST.get("notes", "").strip()

    try:
        amount = Decimal(amount_raw)
        if amount <= 0:
            messages.error(request, "يجب أن يكون مبلغ الدفعة أكبر من الصفر.")
            return redirect("missing_medicines")
    except Exception:
        messages.error(request, "مبلغ الدفعة غير صحيح.")
        return redirect("missing_medicines")

    if amount > invoice.remaining_amount:
        messages.warning(request, f"المبلغ المدخل ({amount}) أكبر من المتبقي على الفاتورة ({invoice.remaining_amount}).")
        return redirect("missing_medicines")

    SupplierPayment.objects.create(
        invoice=invoice,
        amount=amount,
        payment_date=payment_date,
        notes=notes
    )
    messages.success(request, "تم تسجيل الدفعة بنجاح.")
    return redirect("missing_medicines")


# إضافة استرجاع بضاعة لفاتورة
@login_required
def add_return(request, invoice_id):
    if request.method != "POST":
        return redirect("missing_medicines")

    user_profile = request.user.profile
    if not user_profile.is_pharmacy_owner:
        messages.error(request, "ليس لديك صلاحية لتسجيل الإرجاع.")
        return redirect("missing_medicines")

    invoice = get_object_or_404(
        SupplierInvoice,
        id=invoice_id,
        supplier__pharmacy=user_profile.pharmacy
    )

    amount_raw = request.POST.get("amount", "0").strip()
    return_date = request.POST.get("return_date") or timezone.now().date()
    notes = request.POST.get("notes", "").strip()

    try:
        amount = Decimal(amount_raw)
        if amount <= 0:
            messages.error(request, "يجب أن يكون مبلغ الاسترجاع أكبر من الصفر.")
            return redirect("missing_medicines")
    except Exception:
        messages.error(request, "مبلغ الاسترجاع غير صحيح.")
        return redirect("missing_medicines")

    SupplierReturn.objects.create(
        invoice=invoice,
        amount=amount,
        return_date=return_date,
        notes=notes
    )
    messages.success(request, "تم تسجيل الاسترجاع بنجاح.")
    return redirect("missing_medicines")

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
                
            messages.success(request, f"تم نقل ({qty_to_damage} علبة) من دواء ({medicine.trade_name}) إلى التوالف بنجاح.")
        except Exception as e:
            messages.error(request, f"حدث خطأ أثناء معالجة الطلب: {str(e)}")
            
    return redirect('inventory')


# 8. سجل الفواتير والمبيعات
@login_required
def sales_history(request):
    user_profile = request.user.profile
    user_pharmacy = user_profile.pharmacy
    search_query = request.GET.get('search_query', '').strip()
    
    invoices = Invoice.objects.filter(
        pharmacy=user_pharmacy
    ).select_related('cashier').prefetch_related('items__medicine')

    if search_query:
        search_filter = Q()
        if search_query.upper().startswith('INV'):
            search_filter |= Q(invoice_number__iexact=search_query)
        elif search_query.isdigit():
            search_filter |= Q(id=int(search_query))
            search_filter |= Q(invoice_number__endswith=f"-{search_query}")
        elif '-' in search_query or '/' in search_query:
            search_filter |= Q(created_at__icontains=search_query)
        else:
            search_filter |= Q(items__medicine__barcode__iexact=search_query)
            search_filter |= Q(items__medicine__trade_name__icontains=search_query)
            search_filter |= Q(items__medicine__scientific_name__icontains=search_query)
            search_filter |= Q(cashier__username__icontains=search_query)

        invoices = invoices.filter(search_filter).distinct()

    invoices = invoices.order_by('-created_at')

    cashier_summary = []
    if user_profile.is_pharmacy_owner:
        today = timezone.localdate()
        pharmacy_users = User.objects.filter(profile__pharmacy=user_pharmacy)
        
        for u in pharmacy_users:
            print(f"اسم الموظف: {u.username}")
            print(f"تاريخ اليوم في السيرفر: {today}")
            print(f"عدد فواتير هذا الموظف كلياً: {Invoice.objects.filter(cashier=u).count()}")
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
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d') + timedelta(days=1) - timedelta(seconds=1)
            
            if start_date.year < 2000 or start_date.year > 2099 or end_date.year < 2000 or end_date.year > 2099:
                messages.error(request, "يرجى اختيار تواريخ تقرير بين سنتي 2000 و 2099.")
                return redirect('sales_reports')
        except ValueError:
            messages.error(request, "صيغة التاريخ المدخلة غير صحيحة.")
            return redirect('sales_reports')
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

    today = timezone.localdate()
    expired_medicines = Medicine.objects.filter(
        pharmacy=user_pharmacy,
        expiry_date__lt=today,
        quantity__gt=0,
        is_damaged=False
    )
    total_expired_losses = sum((med.quantity * (med.buy_price or 0)) for med in expired_medicines)

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
        'total_sales': int(total_sales or 0),
        'total_discounts_given': int(total_discounts_given or 0),
        'total_invoices_count': total_invoices_count,
        'total_damage_losses': int(total_combined_losses or 0), 
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
    
    total_losses = sum(item.quantity_damaged * (item.medicine.buy_price if item.medicine else 0) for item in damaged_list)
    
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


# =======================================================
# API تفعيل نسخة سطح المكتب
# يستدعيه تطبيق Flutter مرة واحدة عند إدخال رمز التفعيل.
# =======================================================
@csrf_exempt
@require_POST
def desktop_activate(request):
    try:
        data = json.loads(request.body.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse(
            {'ok': False, 'message': 'بيانات الطلب غير صحيحة.'},
            status=400,
        )

    activation_code = str(data.get('activation_code', '')).strip()
    device_fingerprint = str(data.get('device_fingerprint', '')).strip()
    device_name = str(data.get('device_name', '')).strip()[:120]

    if not activation_code or not device_fingerprint:
        return JsonResponse(
            {
                'ok': False,
                'message': 'رمز التفعيل ومعرف الجهاز مطلوبان.',
            },
            status=400,
        )

    if len(device_fingerprint) > 128:
        return JsonResponse(
            {'ok': False, 'message': 'معرف الجهاز غير صالح.'},
            status=400,
        )

    try:
        with transaction.atomic():
            desktop_license = (
                DesktopLicense.objects
                .select_for_update()
                .select_related('pharmacy')
                .get(activation_code=activation_code)
            )

            if not desktop_license.is_valid:
                return JsonResponse(
                    {
                        'ok': False,
                        'message': 'هذا الترخيص غير فعال أو منتهي.',
                    },
                    status=403,
                )

            existing_device = DeviceActivation.objects.filter(
                license=desktop_license,
                device_fingerprint=device_fingerprint,
            ).first()

            if existing_device:
                if not existing_device.is_active:
                    return JsonResponse(
                        {
                            'ok': False,
                            'message': 'هذا الجهاز موقوف من لوحة الإدارة.',
                        },
                        status=403,
                    )

                existing_device.device_name = device_name
                existing_device.save()
            else:
                active_devices_count = desktop_license.devices.filter(
                    is_active=True
                ).count()

                if active_devices_count >= desktop_license.max_devices:
                    return JsonResponse(
                        {
                            'ok': False,
                            'message': 'تم الوصول إلى الحد الأقصى للأجهزة المسموح بها.',
                        },
                        status=403,
                    )

                DeviceActivation.objects.create(
                    license=desktop_license,
                    device_fingerprint=device_fingerprint,
                    device_name=device_name,
                )

    except DesktopLicense.DoesNotExist:
        return JsonResponse(
            {'ok': False, 'message': 'رمز التفعيل غير صحيح.'},
            status=404,
        )

    return JsonResponse(
        {
            'ok': True,
            'message': 'تم تفعيل نسخة سطح المكتب بنجاح.',
            'pharmacy': {
                'id': desktop_license.pharmacy.id,
                'name': desktop_license.pharmacy.name,
            },
            'license': {
                'type': desktop_license.license_type,
                'status': desktop_license.status,
                'expires_at': (
                    desktop_license.expires_at.isoformat()
                    if desktop_license.expires_at else None
                ),
                'max_devices': desktop_license.max_devices,
            },
        },
        status=200,
    )
# =======================================================
# API تسجيل دخول نسخة سطح المكتب
# يستخدمه Flutter عند أول تسجيل دخول عبر الإنترنت،
# ثم يمكنه حفظ بيانات التحقق للعمل دون اتصال لمدة 30 يومًا.
# =======================================================
@csrf_exempt
@require_POST
def desktop_login(request):
    try:
        data = json.loads(request.body.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse(
            {'ok': False, 'message': 'بيانات الطلب غير صحيحة.'},
            status=400,
        )

    username = str(data.get('username', '')).strip()
    password = str(data.get('password', ''))
    device_fingerprint = str(data.get('device_fingerprint', '')).strip()

    if not username or not password or not device_fingerprint:
        return JsonResponse(
            {
                'ok': False,
                'message': 'اسم المستخدم وكلمة المرور ومعرف الجهاز مطلوبة.',
            },
            status=400,
        )

    if len(device_fingerprint) > 128:
        return JsonResponse(
            {'ok': False, 'message': 'معرف الجهاز غير صالح.'},
            status=400,
        )

    user = authenticate(
        request,
        username=username,
        password=password,
    )

    if user is None or not user.is_active:
        return JsonResponse(
            {'ok': False, 'message': 'اسم المستخدم أو كلمة المرور غير صحيحة.'},
            status=401,
        )

    try:
        profile = (
            UserProfile.objects
            .select_related('pharmacy')
            .get(user=user)
        )
    except UserProfile.DoesNotExist:
        return JsonResponse(
            {'ok': False, 'message': 'هذا الحساب غير مرتبط بصيدلية.'},
            status=403,
        )

    if not profile.pharmacy.is_active:
        return JsonResponse(
            {'ok': False, 'message': 'هذه الصيدلية موقوفة حاليًا.'},
            status=403,
        )

    try:
        device = (
            DeviceActivation.objects
            .select_related('license', 'license__pharmacy')
            .get(device_fingerprint=device_fingerprint,license__pharmacy_id=profile.pharmacy_id,)
        )
    except DeviceActivation.DoesNotExist:
        return JsonResponse(
            {
                'ok': False,
                'message': 'هذا الجهاز غير مفعّل. أدخل رمز التفعيل أولًا.',
            },
            status=403,
        )

    desktop_license = device.license

    if not device.is_active:
        return JsonResponse(
            {'ok': False, 'message': 'هذا الجهاز موقوف من لوحة الإدارة.'},
            status=403,
        )

    if desktop_license.pharmacy_id != profile.pharmacy_id:
        return JsonResponse(
            {
                'ok': False,
                'message': 'الحساب لا يتبع للصيدلية المرتبطة بهذا الجهاز.',
            },
            status=403,
        )

    if not desktop_license.is_valid:
        return JsonResponse(
            {'ok': False, 'message': 'ترخيص نسخة سطح المكتب غير فعال أو منتهي.'},
            status=403,
        )

    # تحدّث last_seen_at تلقائيًا لأن الحقل يستخدم auto_now=True.
    device.save(update_fields=['last_seen_at'])

    return JsonResponse(
        {
            'ok': True,
            'message': 'تم تسجيل الدخول بنجاح.',
            'validated_at': timezone.now().isoformat(),
            'offline_grace_days': 30,
            'user': {
                'id': user.id,
                'username': user.username,
                'full_name': user.get_full_name().strip() or user.username,
                'is_owner': profile.is_pharmacy_owner,
            },
            'pharmacy': {
                'id': profile.pharmacy.id,
                'name': profile.pharmacy.name,
            },
            'license': {
                'type': desktop_license.license_type,
                'status': desktop_license.status,
                'expires_at': (
                    desktop_license.expires_at.isoformat()
                    if desktop_license.expires_at else None
                ),
                'max_devices': desktop_license.max_devices,
            },
        },
        status=200,
    )