import json
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent
with open(BASE_DIR / "iraqi_drugs.json", "r", encoding="utf-8") as f:
    IRAQI_MEDICINES = json.load(f)
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
    Medicine, Sale, Invoice, InvoiceItem, Expense,
    DamagedMedicine, PharmacySupplier, UserProfile,
    SupplierInvoice,  SupplierPayment, SupplierReturn, SupplierRefund, AuditLog,
)
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.db.models.functions import Coalesce
from django_ratelimit.decorators import ratelimit


# =======================================================
# 🛡️ حماية Brute-Force العامة لتسجيل الدخول (login_view أدناه)
# =======================================================
def json_ratelimit_view(request, exception):
    """رسالة JSON موحّدة عند تجاوز الحد على أي endpoint من الـ API."""
    return JsonResponse(
        {'ok': False, 'message': 'محاولات كثيرة جداً، حاول لاحقاً.'},
        status=429,
    )


def log_action(request, action, model_name, obj, description, pharmacy=None, user=None):
    """
    تسجيل حركة في AuditLog. تُستدعى بسطر واحد بعد أي عملية حساسة
    (حذف/تعديل دواء، حركات مالية مع المذاخر، تسجيل دخول/خروج...).
    pharmacy/user اختياريان: تُستنتج من request.user.profile إن لم تُمرَّر
    (مفيد في logout حيث يكون request.user قد أصبح AnonymousUser).
    """
    try:
        if pharmacy is None:
            pharmacy = request.user.profile.pharmacy
        if user is None:
            user = request.user

        AuditLog.objects.create(
            pharmacy=pharmacy,
            user=user,
            action=action,
            model_name=model_name,
            object_id=str(obj.pk) if obj is not None else None,
            description=description,
            ip_address=request.META.get('REMOTE_ADDR'),
        )
    except Exception:
        # 🛡️ فشل تسجيل الـ AuditLog لا يجب أن يوقف العملية الأساسية
        # (حذف/دفعة/تسجيل دخول...) التي نجحت فعلاً.
        pass


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
                buy_price = int(request.POST.get('buy_price', 0))
                sell_price = int(request.POST.get('sell_price', 0))

                if quantity < 0 or buy_price < 0 or sell_price < 0:
                    messages.error(request, "لا يمكن إدخال قيم بالسالب للكميات أو الأسعار!")
                    return redirect('inventory')

                new_medicine = Medicine.objects.create(
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
                log_action(
                    request, 'create', 'Medicine', new_medicine,
                    f"إضافة دواء جديد ({new_medicine.trade_name}) بكمية {quantity}"
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
                log_action(
                    request, 'update', 'Medicine', selected_med,
                    f"تحديث كمية ({selected_med.trade_name}) بإضافة {added_qty}"
                )
                messages.success(request, f"تم تحديث كمية {selected_med.trade_name} بنجاح.")

            elif action_type == 'edit_full':
                medicine_id = request.POST.get('medicine_id')
                selected_med = get_object_or_404(Medicine, id=medicine_id, pharmacy=user_pharmacy)

                # 🛡️ ملاحظة: لا يُسمح بتعديل الكمية من هذا الفورم عمداً.
                # أي تصحيح للكمية (كإضافة خاطئة) يجب أن يمر عبر "الإتلاف"
                # بسبب "تعديل كمية" حتى تبقى حركة المخزون موثّقة.
                buy_price = int(request.POST.get('buy_price', 0))
                sell_price = int(request.POST.get('sell_price', 0))

                if buy_price < 0 or sell_price < 0:
                    messages.error(request, "لا يمكن قبول قيم بالسالب!")
                    return redirect('inventory')

                selected_med.barcode = barcode_val
                selected_med.trade_name = request.POST.get('trade_name')
                selected_med.scientific_name = request.POST.get('scientific_name')
                selected_med.category = request.POST.get('category')
                selected_med.buy_price = buy_price
                selected_med.sell_price = sell_price
                selected_med.expiry_date = expiry_date_input
                selected_med.shelf_location = request.POST.get('shelf_location', '')
                selected_med.save()
                log_action(
                    request, 'update', 'Medicine', selected_med,
                    f"تعديل بيانات الدواء ({selected_med.trade_name})"
                )
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

    # 🛡️ عدّ السجلات المرتبطة بكل دواء (مبيعات/عناصر فواتير/إتلاف) لتحديد
    # ما إذا كان يمكن حذفه نهائياً (فقط الأدوية التي لم يُتعامل معها إطلاقاً)
    all_medicines = all_medicines.annotate(
        sales_count=Count('sale', distinct=True),
        invoice_items_count=Count('invoiceitem', distinct=True),
        damage_count=Count('damaged_records', distinct=True),
    )

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
            buy_price = int(request.POST.get('buy_price', 0))
            sell_price = int(request.POST.get('sell_price', 0))

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


# 3.5 حذف الدواء نهائياً (فقط إن لم يكن له أي سجل بيع أو إتلاف)
@login_required
@require_POST
def delete_medicine(request, medicine_id):
    user_profile = request.user.profile
    if not user_profile.is_pharmacy_owner:
        messages.error(request, "عذراً، لا تمتلك صلاحية حذف الأدوية.")
        return redirect('inventory')

    user_pharmacy = user_profile.pharmacy
    medicine = get_object_or_404(Medicine, id=medicine_id, pharmacy=user_pharmacy)

    # 🛡️ لا يُسمح بالحذف النهائي إن كان للدواء أي أثر سابق في النظام
    has_history = (
        Sale.objects.filter(medicine=medicine).exists()
        or InvoiceItem.objects.filter(medicine=medicine).exists()
        or DamagedMedicine.objects.filter(medicine=medicine).exists()
    )

    if has_history:
        messages.error(
            request,
            f"لا يمكن حذف ({medicine.trade_name}) نهائياً لوجود سجل مبيعات أو إتلاف مرتبط به. "
            "يمكنك إتلافه بدلاً من ذلك إن أردت سحبه من المخزن."
        )
        return redirect('inventory')

    medicine_name = medicine.trade_name
    medicine_id = medicine.id
    medicine.delete()
    log_action(
        request, 'delete', 'Medicine', None,
        f"حذف الدواء ({medicine_name}) - ID: {medicine_id} نهائياً من المخزن."
    )
    messages.success(request, f"تم حذف ({medicine_name}) نهائياً من المخزن.")
    return redirect('inventory')


# 4. شاشة نقطة البيع (POS)
@login_required
def pos(request):
    user_pharmacy = request.user.profile.pharmacy
    today = timezone.localdate()

    medicines = Medicine.objects.filter(
        pharmacy=user_pharmacy,
        quantity__gt=0,
        is_damaged=False,
        expiry_date__gt=today,
    )

    search_query = request.GET.get('search_med', '').strip()
    if search_query:
        medicines = medicines.filter(
            Q(barcode__iexact=search_query) |
            Q(trade_name__icontains=search_query) |
            Q(scientific_name__icontains=search_query)
        )

    if request.method == 'POST':
        medicine_ids = request.POST.getlist('medicine_ids[]')
        quantities = request.POST.getlist('quantities[]')
        discount_value_raw = request.POST.get('discount_value', '0').strip()
        discount_type = request.POST.get('discount_type', 'amount')

        if not medicine_ids:
            messages.error(request, "لا يمكنك حفظ فاتورة فارغة.")
            return redirect('pos')

        if len(medicine_ids) != len(quantities):
            messages.error(request, "بيانات الأدوية والكميات غير متطابقة.")
            return redirect('pos')

        if discount_type not in ('amount', 'percent'):
            messages.error(request, "نوع الخصم غير صالح.")
            return redirect('pos')

        try:
            discount_value = int(discount_value_raw)
        except (TypeError, ValueError):
            messages.error(request, "قيمة الخصم يجب أن تكون رقماً صحيحاً من دون كسور.")
            return redirect('pos')

        if discount_value < 0:
            messages.error(request, "لا يمكن أن يكون الخصم سالباً.")
            return redirect('pos')

        if discount_type == 'percent' and discount_value > 100:
            messages.error(request, "نسبة الخصم لا يمكن أن تتجاوز 100%.")
            return redirect('pos')

        try:
            with transaction.atomic():
                invoice = Invoice.objects.create(
                    pharmacy=user_pharmacy,
                    cashier=request.user,
                    total_amount=0,
                    discount=0,
                    final_amount=0,
                )

                total_invoice_amount = 0

                for med_id, qty_str in zip(medicine_ids, quantities):
                    try:
                        qty_sold = int(qty_str)
                    except (TypeError, ValueError):
                        raise ValueError("كمية البيع يجب أن تكون رقماً صحيحاً.")

                    if qty_sold <= 0:
                        raise ValueError("كمية البيع يجب أن تكون أكبر من الصفر.")

                    try:
                        selected_med = Medicine.objects.select_for_update().get(
                            id=med_id,
                            pharmacy=user_pharmacy,
                        )
                    except Medicine.DoesNotExist:
                        raise ValueError("أحد الأدوية المختارة غير موجود في مخزونك.")

                    if selected_med.is_damaged:
                        raise ValueError(f"الدواء {selected_med.trade_name} معزول ولا يمكن بيعه.")

                    if selected_med.expiry_date <= today:
                        raise ValueError(f"الدواء {selected_med.trade_name} منتهي الصلاحية ولا يمكن بيعه.")

                    if selected_med.quantity < qty_sold:
                        raise ValueError(
                            f"الكمية المطلوبة من {selected_med.trade_name} غير متوفرة. "
                            f"المتاح: {selected_med.quantity}"
                        )

                    unit_price = int(selected_med.sell_price)
                    total_item_price = unit_price * qty_sold
                    total_invoice_amount += total_item_price

                    InvoiceItem.objects.create(
                        invoice=invoice,
                        medicine=selected_med,
                        quantity=qty_sold,
                        unit_price=unit_price,
                        total_price=total_item_price,
                    )

                    selected_med.quantity -= qty_sold
                    selected_med.save(update_fields=['quantity'])

                if discount_type == 'percent':
                    applied_discount = (total_invoice_amount * discount_value) // 100
                else:
                    if discount_value > total_invoice_amount:
                        raise ValueError("قيمة الخصم أكبر من إجمالي الفاتورة.")
                    applied_discount = discount_value

                invoice.total_amount = total_invoice_amount
                invoice.discount = applied_discount
                invoice.final_amount = total_invoice_amount - applied_discount
                invoice.full_clean()
                invoice.save()

            log_action(
                request, 'create', 'Invoice', invoice,
                f"إنشاء فاتورة بيع #{invoice.invoice_number} بصافي {invoice.final_amount}"
            )
            messages.success(
                request,
                f"تم حفظ الفاتورة {invoice.invoice_number} بنجاح."
            )
            return redirect('pos')

        except ValueError as e:
            messages.error(request, str(e))
            return redirect('pos')
        except Exception:
            messages.error(request, "تعذر حفظ الفاتورة. يرجى المحاولة مرة أخرى.")
            return redirect('pos')

    recent_invoices = Invoice.objects.filter(
        pharmacy=user_pharmacy
    ).prefetch_related('items__medicine').order_by('-created_at')[:10]

    return render(request, 'pharmacy/pos.html', {
        'medicines': medicines,
        'recent_invoices': recent_invoices,
        'search_query': search_query,
        'pharmacy_name': user_pharmacy.name,
    })


# 5. إرجاع الفاتورة
@login_required
@require_POST
def refund_sale(request, sale_id):
    user_pharmacy = request.user.profile.pharmacy

    with transaction.atomic():
        invoice = get_object_or_404(
            Invoice.objects.select_for_update(),
            id=sale_id,
            pharmacy=user_pharmacy,
        )

        if invoice.is_refunded:
            messages.warning(request, "هذه الفاتورة تم إرجاعها مسبقاً.")
            return redirect('pos')

        for item in invoice.items.select_related('medicine'):
            medicine = Medicine.objects.select_for_update().get(id=item.medicine_id)
            medicine.quantity += item.quantity
            medicine.save(update_fields=['quantity'])

        invoice.is_refunded = True
        invoice.save(update_fields=['is_refunded'])

    log_action(
        request, 'update', 'Invoice', invoice,
        f"إرجاع فاتورة بيع #{invoice.invoice_number} وإعادة الأدوية للمخزن"
    )
    messages.success(
        request,
        "تم إرجاع الفاتورة بنجاح وإعادة الأدوية إلى المخزن."
    )
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
            'invoices__returns',
            'invoices__refunds'
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

        # ----- بناء كشف الحساب (حركات مرتبة زمنياً + رصيد متراكم) -----
        statement_entries = []
        for invoice in invoices:
            statement_entries.append({
                "date": invoice.invoice_date,
                "created_at": invoice.created_at,
                "type": "invoice",
                "type_label": "فاتورة",
                "label": f"فاتورة رقم #{invoice.invoice_number}",
                "debit": invoice.original_amount,
                "credit_payment": Decimal("0"),
                "credit_return": Decimal("0"),
                "debit_refund": Decimal("0"),
                "notes": invoice.notes,
            })
            for payment in invoice.payments.all():
                statement_entries.append({
                    "date": payment.payment_date,
                    "created_at": payment.created_at,
                    "type": "payment",
                    "type_label": "دفعة",
                    "label": f"دفعة نقدية - فاتورة #{invoice.invoice_number}",
                    "debit": Decimal("0"),
                    "credit_payment": payment.amount,
                    "credit_return": Decimal("0"),
                    "debit_refund": Decimal("0"),
                    "notes": payment.notes,
                })
            for ret in invoice.returns.all():
                statement_entries.append({
                    "date": ret.return_date,
                    "created_at": ret.created_at,
                    "type": "return",
                    "type_label": "استرجاع",
                    "label": f"استرجاع بضاعة - فاتورة #{invoice.invoice_number}"
                              + (f" ({ret.reason})" if ret.reason else ""),
                    "debit": Decimal("0"),
                    "credit_payment": Decimal("0"),
                    "credit_return": ret.amount,
                    "debit_refund": Decimal("0"),
                    "notes": ret.notes,
                })
            for refund in invoice.refunds.all():
                statement_entries.append({
                    "date": refund.refund_date,
                    "created_at": refund.created_at,
                    "type": "refund",
                    "type_label": "استلام دين",
                    "label": f"استلام مبلغ من المذخر - فاتورة #{invoice.invoice_number}",
                    "debit": Decimal("0"),
                    "credit_payment": Decimal("0"),
                    "credit_return": Decimal("0"),
                    "debit_refund": refund.amount,
                    "notes": refund.notes,
                })

        # ترتيب حسب تاريخ الحركة (الذي يدخله المستخدم) أولاً،
        # وعند تساوي التاريخ يُستخدم وقت التنفيذ الفعلي (created_at)
        # ليعكس الترتيب الحقيقي للعمليات كما نفّذها الصيدلي بالضبط.
        statement_entries.sort(key=lambda e: (e["date"], e["created_at"]))

        running_balance = Decimal("0")
        statement_total_debit = Decimal("0")
        statement_total_payment = Decimal("0")
        statement_total_return = Decimal("0")
        statement_total_refund = Decimal("0")
        for entry in statement_entries:
            running_balance += (
                entry["debit"] + entry["debit_refund"]
                - entry["credit_payment"] - entry["credit_return"]
            )
            entry["balance"] = running_balance
            statement_total_debit += entry["debit"]
            statement_total_payment += entry["credit_payment"]
            statement_total_return += entry["credit_return"]
            statement_total_refund += entry["debit_refund"]

        supplier_data.append({
            "supplier": supplier,
            "invoices": invoices,
            "total_purchase": total_purchase,
            "total_debt": supplier_debt,
            "invoice_count": supplier.invoices_count,
            "statement_entries": statement_entries,
            "statement_total_debit": statement_total_debit,
            "statement_total_payment": statement_total_payment,
            "statement_total_return": statement_total_return,
            "statement_total_refund": statement_total_refund,
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
        
    supplier = PharmacySupplier.objects.create(
        pharmacy=pharmacy,
        name=name,
        phone=phone
    )
    log_action(
        request, 'create', 'PharmacySupplier', supplier,
        f"إضافة مذخر جديد ({supplier.name})"
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

    log_action(
        request, 'update', 'PharmacySupplier', supplier,
        f"تعديل بيانات المذخر ({supplier.name})"
    )
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

    supplier_name = supplier.name
    supplier.delete()
    log_action(
        request, 'delete', 'PharmacySupplier', None,
        f"حذف المذخر ({supplier_name})"
    )
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

    # 1. قراءة الحقول الثلاثة فقط (مع دعم name="first_payment" من الـ HTML)
    invoice_number = request.POST.get("invoice_number", "").strip()
    original_amount_raw = request.POST.get("original_amount", "0").strip()
    paid_amount_raw = (request.POST.get("first_payment") or request.POST.get("paid_amount", "0")).strip()

    # 2. التاريخ يُسجّل تلقائياً بلحظة الحفظ
    invoice_date = timezone.now().date()

    # 3. التحقق من رقم الفاتورة
    if not invoice_number:
        messages.error(request, "رقم الفاتورة مطلوب.")
        return redirect("missing_medicines")

    # 4. التحقق من مبلغ الفاتورة الأصلي
    try:
        original_amount = float(original_amount_raw)
    except (TypeError, ValueError):
        messages.error(request, "مبلغ الفاتورة غير صحيح.")
        return redirect("missing_medicines")

    if original_amount <= 0:
        messages.error(request, "مبلغ الفاتورة يجب أن يكون أكبر من الصفر.")
        return redirect("missing_medicines")

    # 5. التحقق من المبلغ المدفوع
    paid_amount = 0.0
    if paid_amount_raw:
        try:
            paid_amount = float(paid_amount_raw)
        except (TypeError, ValueError):
            messages.error(request, "المبلغ المدفوع غير صحيح.")
            return redirect("missing_medicines")

    if paid_amount < 0:
        messages.error(request, "المبلغ المدفوع لا يمكن أن يكون بالسالب.")
        return redirect("missing_medicines")

    if paid_amount > original_amount:
        messages.error(request, "المبلغ المدفوع لا يمكن أن يكون أكبر من المبلغ الأصلي للفاتورة.")
        return redirect("missing_medicines")

    with transaction.atomic():
        supplier = get_object_or_404(
            PharmacySupplier.objects.select_for_update(),
            id=supplier_id,
            pharmacy=user_profile.pharmacy,
        )

        if SupplierInvoice.objects.filter(
            supplier=supplier,
            invoice_number=invoice_number,
        ).exists():
            messages.warning(request, "رقم الفاتورة مستخدم مسبقاً لهذا المذخر.")
            return redirect("missing_medicines")

        # إنشاء الفاتورة
        invoice = SupplierInvoice.objects.create(
            supplier=supplier,
            invoice_number=invoice_number,
            invoice_date=invoice_date,
            original_amount=original_amount,
            notes="",
        )

        # 6. إن كان هناك مبلغ مدفوع (أكبر من 0)، تُسجّل حركة دفع
        if paid_amount > 0:
            payment_note = "تم الدفع بالكامل عند إنشاء الفاتورة." if paid_amount == original_amount else "الدفعة الأولى عند إنشاء الفاتورة."
            SupplierPayment.objects.create(
                invoice=invoice,
                amount=paid_amount,
                payment_date=invoice.invoice_date,
                notes=payment_note
            )

        # تحديث حالة الفاتورة تلقائياً بناءً على المدفوعات
        invoice.update_status()

    log_action(
        request, 'create', 'SupplierInvoice', invoice,
        f"إضافة فاتورة مذخر #{invoice.invoice_number} - {supplier.name} - المبلغ: {original_amount}"
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

    amount_raw = request.POST.get("amount", "0").strip()
    payment_date = request.POST.get("payment_date") or timezone.now().date()
    notes = request.POST.get("notes", "").strip()

    try:
        amount = int(amount_raw)
        if amount <= 0:
            messages.error(request, "يجب أن يكون مبلغ الدفعة أكبر من الصفر.")
            return redirect("missing_medicines")
    except (TypeError, ValueError):
        messages.error(request, "مبلغ الدفعة غير صحيح.")
        return redirect("missing_medicines")

    with transaction.atomic():
        invoice = get_object_or_404(
            SupplierInvoice.objects.select_for_update(),
            id=invoice_id,
            supplier__pharmacy=user_profile.pharmacy,
        )

        if invoice.remaining_amount <= 0:
            messages.warning(request, "لا يوجد مبلغ مستحق دفعه على هذه الفاتورة.")
            return redirect("missing_medicines")

        if amount > invoice.remaining_amount:
            messages.warning(request, f"المبلغ المدخل ({amount}) أكبر من المتبقي على الفاتورة ({invoice.remaining_amount}).")
            return redirect("missing_medicines")

        payment = SupplierPayment.objects.create(
            invoice=invoice,
            amount=amount,
            payment_date=payment_date,
            notes=notes,
        )
        invoice.update_status()

    log_action(
        request, 'create', 'SupplierPayment', payment,
        f"تسجيل دفعة بمبلغ {amount} لفاتورة #{invoice.invoice_number} - {invoice.supplier.name}"
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

    amount_raw = request.POST.get("amount", "0").strip()
    return_date = request.POST.get("return_date") or timezone.now().date()
    notes = request.POST.get("notes", "").strip()

    try:
        amount = int(amount_raw)
        if amount <= 0:
            messages.error(request, "يجب أن يكون مبلغ الاسترجاع أكبر من الصفر.")
            return redirect("missing_medicines")
    except (TypeError, ValueError):
        messages.error(request, "مبلغ الاسترجاع غير صحيح.")
        return redirect("missing_medicines")

    with transaction.atomic():
        invoice = get_object_or_404(
            SupplierInvoice.objects.select_for_update(),
            id=invoice_id,
            supplier__pharmacy=user_profile.pharmacy,
        )

        available_to_return = invoice.original_amount - invoice.total_returned
        if amount > available_to_return:
            messages.warning(
                request,
                f"مبلغ الاسترجاع ({amount}) أكبر من المتاح للإرجاع ({available_to_return}).",
            )
            return redirect("missing_medicines")

        supplier_return = SupplierReturn.objects.create(
            invoice=invoice,
            amount=amount,
            return_date=return_date,
            notes=notes,
        )
        invoice.update_status()

    log_action(
        request, 'create', 'SupplierReturn', supplier_return,
        f"تسجيل استرجاع بمبلغ {amount} لفاتورة #{invoice.invoice_number} - {invoice.supplier.name}"
    )
    messages.success(request, "تم تسجيل الاسترجاع بنجاح.")
    return redirect("missing_medicines")


# استلام مبلغ من المذخر (عندما يكون المذخر مديناً للصيدلية على فاتورة معينة)
@login_required
def settle_supplier_debt(request, invoice_id):
    if request.method != "POST":
        return redirect("missing_medicines")

    user_profile = request.user.profile
    if not user_profile.is_pharmacy_owner:
        messages.error(request, "ليس لديك صلاحية لتنفيذ هذا الإجراء.")
        return redirect("missing_medicines")

    invoice = get_object_or_404(
        SupplierInvoice,
        id=invoice_id,
        supplier__pharmacy=user_profile.pharmacy
    )

    with transaction.atomic():
        # إعادة قراءة الفاتورة داخل transaction لتفادي أي تعارض في نفس اللحظة
        invoice = SupplierInvoice.objects.select_for_update().get(id=invoice.id)
        remaining = invoice.remaining_amount

        if remaining >= 0:
            messages.warning(request, "لا يوجد رصيد مستحق لنا على هذا المذخر لهذه الفاتورة.")
            return redirect("missing_medicines")

        amount_to_receive = abs(remaining)

        refund = SupplierRefund.objects.create(
            invoice=invoice,
            amount=amount_to_receive,
            refund_date=timezone.now().date(),
            notes="تصفير رصيد - استلام مستحقات من المذخر."
        )
        invoice.update_status()

    log_action(
        request, 'update', 'SupplierRefund', refund,
        f"استلام {amount_to_receive} من المذخر {invoice.supplier.name} وتصفير رصيد فاتورة #{invoice.invoice_number}"
    )
    messages.success(request, "تم تسجيل استلام المبلغ من المذخر وتصفير الرصيد.")
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

                damaged_record = DamagedMedicine.objects.create(
                    pharmacy=user_pharmacy,
                    medicine=medicine,
                    quantity_damaged=qty_to_damage,
                    unit_cost=medicine.buy_price,
                    reason=damage_reason,
                    notes=damage_notes
                )

            log_action(
                request, 'create', 'DamagedMedicine', damaged_record,
                f"نقل {qty_to_damage} من ({medicine.trade_name}) إلى التوالف - السبب: {damage_reason}"
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
    refunded_invoices_count = Invoice.objects.filter(
        pharmacy=user_pharmacy,
        created_at__range=(start_date, end_date),
        is_refunded=True,
    ).count()
    total_discounts_given = invoices.aggregate(Sum('discount'))['discount__sum'] or 0.0
    total_expenses = Expense.objects.filter(
        pharmacy=user_pharmacy,
        expense_date__range=(start_date.date(), end_date.date()),
    ).aggregate(total=Sum('amount'))['total'] or 0

    # الرصيد الحالي للمذاخر لا يرتبط بفترة التقرير: تُحسب كل الفواتير
    # مع حركاتها الفعلية (دفعات، استرجاعات، ومبالغ مستلمة من المذخر).
    supplier_invoices = SupplierInvoice.objects.filter(
        supplier__pharmacy=user_pharmacy,
    ).prefetch_related('payments', 'returns', 'refunds')
    total_supplier_debt = sum(
        invoice.remaining_amount for invoice in supplier_invoices
    )

    today = timezone.localdate()
    expired_medicines = Medicine.objects.filter(
        pharmacy=user_pharmacy,
        expiry_date__lt=today,
        quantity__gt=0,
        is_damaged=False
    )
    total_expired_losses = sum((med.quantity * (med.buy_price or 0)) for med in expired_medicines)

    damaged_losses_query = DamagedMedicine.objects.filter(
        pharmacy=user_pharmacy
    ).exclude(
        reason='quantity_correction'
    ).annotate(
        loss_amount=F('quantity_damaged') * F('unit_cost')
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
        'refunded_invoices_count': refunded_invoices_count,
        'total_supplier_debt': int(total_supplier_debt),
        'total_expenses': int(total_expenses),
        'net_after_expenses': int(total_sales - total_expenses),
        'total_damage_losses': int(total_combined_losses or 0), 
        'top_selling_items': top_selling_items,
        'stagnant_medicines': stagnant_medicines,
        'pharmacy_name': user_pharmacy.name
    }
    return render(request, 'pharmacy/reports.html', context)


def _expense_redirect_url(request):
    query_string = request.POST.get('next_query', '')
    return f"{redirect('expenses').url}?{query_string}" if query_string else redirect('expenses').url


@login_required
def expenses(request):
    user_profile = request.user.profile
    if not user_profile.is_pharmacy_owner:
        messages.error(request, 'عذراً، هذه الصفحة مخصصة للإدارة فقط.')
        return redirect('pharmacy_dashboard')

    pharmacy = user_profile.pharmacy
    today = timezone.localdate()
    start_date_str = request.GET.get('start_date', '')
    end_date_str = request.GET.get('end_date', '')
    expense_type = request.GET.get('expense_type', '')
    expenses_queryset = Expense.objects.filter(pharmacy=pharmacy)

    try:
        if start_date_str:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            expenses_queryset = expenses_queryset.filter(expense_date__gte=start_date)
        if end_date_str:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            expenses_queryset = expenses_queryset.filter(expense_date__lte=end_date)
        if start_date_str and end_date_str and start_date > end_date:
            raise ValueError
    except ValueError:
        messages.error(request, 'يرجى إدخال فترة زمنية صحيحة.')
        return redirect('expenses')

    if expense_type:
        valid_types = dict(Expense.EXPENSE_TYPES)
        if expense_type not in valid_types:
            messages.error(request, 'نوع المصروف المحدد غير صحيح.')
            return redirect('expenses')
        expenses_queryset = expenses_queryset.filter(expense_type=expense_type)

    chart_data = list(
        expenses_queryset.values('expense_type')
        .annotate(total=Sum('amount'))
        .order_by('expense_type')
    )
    labels_by_type = dict(Expense.EXPENSE_TYPES)
    chart_labels = [labels_by_type[row['expense_type']] for row in chart_data]
    chart_amounts = [row['total'] for row in chart_data]
    today_expenses = Expense.objects.filter(pharmacy=pharmacy, expense_date=today)

    return render(request, 'pharmacy/expenses.html', {
        'expenses': expenses_queryset,
        'expense_types': Expense.EXPENSE_TYPES,
        'selected_expense_type': expense_type,
        'start_date': start_date_str,
        'end_date': end_date_str,
        'today_total': today_expenses.aggregate(total=Sum('amount'))['total'] or 0,
        'today_count': today_expenses.count(),
        'chart_labels': json.dumps(chart_labels, ensure_ascii=False),
        'chart_amounts': json.dumps(chart_amounts),
        'next_query': request.GET.urlencode(),
    })


@login_required
@require_POST
def add_expense(request):
    user_profile = request.user.profile
    if not user_profile.is_pharmacy_owner:
        messages.error(request, 'ليس لديك صلاحية لإضافة مصروف.')
        return redirect('pharmacy_dashboard')

    expense_type = request.POST.get('expense_type', '')
    expense_date_raw = request.POST.get('expense_date', '')
    amount_raw = request.POST.get('amount', '').strip()
    notes = request.POST.get('notes', '').strip()
    if expense_type not in dict(Expense.EXPENSE_TYPES):
        messages.error(request, 'يرجى اختيار نوع مصروف صحيح.')
        return redirect(_expense_redirect_url(request))
    try:
        expense_date = datetime.strptime(expense_date_raw, '%Y-%m-%d').date()
        amount = int(amount_raw)
    except (TypeError, ValueError):
        messages.error(request, 'يرجى إدخال تاريخ ومبلغ صحيحين.')
        return redirect(_expense_redirect_url(request))
    if amount <= 0:
        messages.error(request, 'المبلغ يجب أن يكون أكبر من صفر.')
        return redirect(_expense_redirect_url(request))

    expense = Expense.objects.create(
        pharmacy=user_profile.pharmacy, expense_type=expense_type,
        expense_date=expense_date, amount=amount, notes=notes,
    )
    log_action(request, 'create', 'Expense', expense, f'إضافة مصروف {expense.get_expense_type_display()} بقيمة {amount} د.ع')
    messages.success(request, 'تمت إضافة المصروف بنجاح.')
    return redirect(_expense_redirect_url(request))


@login_required
@require_POST
def edit_expense(request, expense_id):
    user_profile = request.user.profile
    if not user_profile.is_pharmacy_owner:
        messages.error(request, 'ليس لديك صلاحية لتعديل المصروفات.')
        return redirect('pharmacy_dashboard')
    expense = get_object_or_404(Expense, pk=expense_id, pharmacy=user_profile.pharmacy)
    expense_type = request.POST.get('expense_type', '')
    expense_date_raw = request.POST.get('expense_date', '')
    amount_raw = request.POST.get('amount', '').strip()
    notes = request.POST.get('notes', '').strip()
    try:
        expense_date = datetime.strptime(expense_date_raw, '%Y-%m-%d').date()
        amount = int(amount_raw)
    except (TypeError, ValueError):
        messages.error(request, 'يرجى إدخال تاريخ ومبلغ صحيحين.')
        return redirect(_expense_redirect_url(request))
    if expense_type not in dict(Expense.EXPENSE_TYPES) or amount <= 0:
        messages.error(request, 'بيانات المصروف غير صحيحة.')
        return redirect(_expense_redirect_url(request))
    expense.expense_type, expense.expense_date = expense_type, expense_date
    expense.amount, expense.notes = amount, notes
    expense.save(update_fields=['expense_type', 'expense_date', 'amount', 'notes'])
    log_action(request, 'update', 'Expense', expense, f'تعديل مصروف {expense.get_expense_type_display()} بقيمة {amount} د.ع')
    messages.success(request, 'تم تعديل المصروف بنجاح.')
    return redirect(_expense_redirect_url(request))


@login_required
@require_POST
def delete_expense(request, expense_id):
    user_profile = request.user.profile
    if not user_profile.is_pharmacy_owner:
        messages.error(request, 'ليس لديك صلاحية لحذف المصروفات.')
        return redirect('pharmacy_dashboard')
    expense = get_object_or_404(Expense, pk=expense_id, pharmacy=user_profile.pharmacy)
    description = f'حذف مصروف {expense.get_expense_type_display()} بقيمة {expense.amount} د.ع'
    expense.delete()
    log_action(request, 'delete', 'Expense', None, description)
    messages.success(request, 'تم حذف المصروف بنجاح.')
    return redirect(_expense_redirect_url(request))


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
    
    # 🛡️ الاعتماد على خاصية total_loss المحمية بالموديل، والتي تستثني
    # تلقائياً عمليات "تعديل الكمية" من إجمالي الخسائر المالية.
    total_losses = sum(item.total_loss for item in damaged_list)
    
    return render(request, 'pharmacy/damaged_medicines.html', {
        'damaged_list': damaged_list,
        'total_losses': total_losses,
        'pharmacy_name': user_pharmacy.name
    })


# تسجيل الدخول والخروج
@ratelimit(key='ip', rate='15/m', method='POST', block=True)
@ratelimit(key='post:username', rate='6/m', method='POST', block=True)
def login_view(request):
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(username=username, password=password)
            if user is not None:
                login(request, user)
                try:
                    pharmacy = user.profile.pharmacy
                    log_action(
                        request, 'login', 'User', None,
                        f"تسجيل دخول: {user.username}",
                        pharmacy=pharmacy, user=user,
                    )
                except ObjectDoesNotExist:
                    pass
                return redirect('pharmacy_dashboard')
    else:
        form = AuthenticationForm()
    return render(request, 'pharmacy/login.html', {'form': form})


def logout_view(request):
    if request.user.is_authenticated:
        try:
            pharmacy = request.user.profile.pharmacy
            log_action(
                request, 'logout', 'User', None,
                f"تسجيل خروج: {request.user.username}",
                pharmacy=pharmacy, user=request.user,
            )
        except ObjectDoesNotExist:
            pass
    logout(request)
    return redirect('login')


LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'pharmacy_dashboard'
LOGOUT_REDIRECT_URL = 'login'


def landing_page(request):
    return render(request, 'pharmacy/landing.html')