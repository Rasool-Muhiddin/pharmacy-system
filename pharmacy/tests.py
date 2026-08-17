from datetime import date

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from .models import DamagedMedicine, Invoice, Medicine, PharmacyBranch


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