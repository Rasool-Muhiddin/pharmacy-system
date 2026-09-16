from datetime import date, datetime

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    DamagedMedicine, Expense, Invoice, Medicine, PharmacyBranch, PharmacySupplier,
    SupplierInvoice, SupplierPayment, UserProfile,
)


class ProjectUrlTests(SimpleTestCase):
    def test_healthz_returns_ok(self):
        response = self.client.get(reverse("healthz"), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")

    def test_healthz_accepts_get_only(self):
        response = self.client.post(reverse("healthz"), secure=True)

        self.assertEqual(response.status_code, 405)

    def test_admin_uses_configured_url(self):
        self.assertEqual(
            reverse("admin:index"),
            f"/{settings.ADMIN_URL}",
        )


class InvoiceSequenceTests(TestCase):
    def setUp(self):
        self.pharmacy = PharmacyBranch.objects.create(name="صيدلية الاختبار")

    def test_generates_sequential_numbers_per_pharmacy(self):
        first_invoice = Invoice.objects.create(pharmacy=self.pharmacy)
        second_invoice = Invoice.objects.create(pharmacy=self.pharmacy)

        self.assertEqual(first_invoice.invoice_number, "INV-1")
        self.assertEqual(second_invoice.invoice_number, "INV-2")

        self.pharmacy.refresh_from_db()
        self.assertEqual(self.pharmacy.invoice_sequence, 2)

    def test_initializes_counter_from_existing_invoice_numbers(self):
        Invoice.objects.create(
            pharmacy=self.pharmacy,
            invoice_number="INV-27",
        )

        next_invoice = Invoice.objects.create(pharmacy=self.pharmacy)

        self.assertEqual(next_invoice.invoice_number, "INV-28")

        self.pharmacy.refresh_from_db()
        self.assertEqual(self.pharmacy.invoice_sequence, 28)

    def test_each_pharmacy_has_its_own_sequence(self):
        another_pharmacy = PharmacyBranch.objects.create(name="صيدلية ثانية")

        first_invoice = Invoice.objects.create(pharmacy=self.pharmacy)
        other_invoice = Invoice.objects.create(pharmacy=another_pharmacy)

        self.assertEqual(first_invoice.invoice_number, "INV-1")
        self.assertEqual(other_invoice.invoice_number, "INV-1")

    def test_legacy_invoice_without_pharmacy_gets_uuid_number(self):
        invoice = Invoice.objects.create()

        self.assertRegex(
            invoice.invoice_number,
            r"^INV-[0-9A-F]{6}$",
        )

    def test_damage_loss_uses_cost_at_the_time_of_damage(self):
        medicine = Medicine.objects.create(
            pharmacy=self.pharmacy,
            trade_name="دواء اختبار",
            scientific_name="Test medicine",
            category="tablet",
            quantity=10,
            buy_price=1000,
            sell_price=1500,
            expiry_date=date(2030, 1, 1),
        )
        damaged = DamagedMedicine.objects.create(
            pharmacy=self.pharmacy,
            medicine=medicine,
            quantity_damaged=3,
            reason="broken",
        )

        medicine.buy_price = 2000
        medicine.save(update_fields=["buy_price"])
        damaged.refresh_from_db()

        self.assertEqual(damaged.unit_cost, 1000)
        self.assertEqual(damaged.total_loss, 3000)


class ExpenseTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        self.pharmacy = PharmacyBranch.objects.create(name='صيدلية المصروفات')
        self.owner = User.objects.create_user(username='owner', password='test-password')
        UserProfile.objects.create(user=self.owner, pharmacy=self.pharmacy, is_pharmacy_owner=True)
        self.client.force_login(self.owner)

    def test_add_expense_and_filter_by_date(self):
        response = self.client.post(reverse('add_expense'), {
            'expense_type': 'rent', 'expense_date': '2026-09-10', 'amount': '50000', 'notes': 'إيجار شهري',
        })
        self.assertRedirects(response, reverse('expenses'))
        self.assertEqual(Expense.objects.filter(pharmacy=self.pharmacy).count(), 1)
        response = self.client.get(reverse('expenses'), {'start_date': '2026-09-10', 'end_date': '2026-09-10'})
        self.assertContains(response, '50,000')

    def test_rejects_non_positive_expense_amount(self):
        response = self.client.post(reverse('add_expense'), {
            'expense_type': 'rent', 'expense_date': '2026-09-10', 'amount': '0', 'notes': '',
        })
        self.assertRedirects(response, reverse('expenses'))
        self.assertFalse(Expense.objects.exists())

    def test_edit_and_delete_expense(self):
        expense = Expense.objects.create(
            pharmacy=self.pharmacy,
            expense_type='utilities',
            expense_date=date(2026, 9, 10),
            amount=25000,
            notes='فاتورة كهرباء',
        )
        response = self.client.post(reverse('edit_expense', args=[expense.id]), {
            'expense_type': 'maintenance', 'expense_date': '2026-09-11', 'amount': '30000', 'notes': 'صيانة',
        })
        self.assertRedirects(response, reverse('expenses'))
        expense.refresh_from_db()
        self.assertEqual((expense.expense_type, expense.amount), ('maintenance', 30000))
        response = self.client.post(reverse('delete_expense', args=[expense.id]))
        self.assertRedirects(response, reverse('expenses'))
        self.assertFalse(Expense.objects.filter(pk=expense.id).exists())

    def test_report_uses_current_supplier_debt_and_filtered_invoice_count(self):
        supplier = PharmacySupplier.objects.create(pharmacy=self.pharmacy, name='مذخر الاختبار')
        supplier_invoice = SupplierInvoice.objects.create(
            supplier=supplier, invoice_number='SUP-1', invoice_date=date(2026, 1, 1), original_amount=100000,
        )
        SupplierPayment.objects.create(invoice=supplier_invoice, amount=30000, payment_date=date(2026, 9, 1))
        report_invoice = Invoice.objects.create(
            pharmacy=self.pharmacy, invoice_number='INV-REPORT', final_amount=50000,
        )
        Invoice.objects.filter(pk=report_invoice.pk).update(
            created_at=timezone.make_aware(datetime(2026, 9, 10, 12, 0)),
        )
        refunded_invoice = Invoice.objects.create(
            pharmacy=self.pharmacy, invoice_number='INV-REFUND', final_amount=25000, is_refunded=True,
        )
        Invoice.objects.filter(pk=refunded_invoice.pk).update(
            created_at=timezone.make_aware(datetime(2026, 9, 11, 12, 0)),
        )
        response = self.client.get(reverse('sales_reports'), {
            'start_date': '2026-09-01', 'end_date': '2026-09-30',
        })
        self.assertEqual(response.context['total_supplier_debt'], 70000)
        self.assertEqual(response.context['total_invoices_count'], 1)
        self.assertEqual(response.context['refunded_invoices_count'], 1)
