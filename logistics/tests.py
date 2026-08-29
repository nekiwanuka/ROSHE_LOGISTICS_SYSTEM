from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .forms import (
    PaymentTransactionForm,
    QuoteContainerFormSet,
    QuoteForm,
    QuoteInvoiceConversionForm,
)
from .models import Client, CustomUser, Loading, Payment, PaymentTransaction, Quote
from .payment_stamp import PaymentVerificationStamp


class MixedFCLDocumentTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_superuser(
            username="fcl-admin", password="test-password"
        )
        self.client.force_login(self.user)
        self.customer = Client.objects.create(
            name="Mixed Container Client",
            contact_person="Accounts",
            phone="0700000000",
            address="Kampala",
            created_by=self.user,
        )

    def _container_management_data(self):
        return {
            "containers-TOTAL_FORMS": "3",
            "containers-INITIAL_FORMS": "0",
            "containers-MIN_NUM_FORMS": "0",
            "containers-MAX_NUM_FORMS": "1000",
            "containers-0-quantity": "1",
            "containers-0-container_size": "20ft",
            "containers-0-rate_per_container": "1000.00",
            "containers-0-pvoc_per_container": "10.00",
            "containers-0-container_numbers": "MSCU001",
            "containers-1-quantity": "1",
            "containers-1-container_size": "20ft",
            "containers-1-rate_per_container": "1000.00",
            "containers-1-pvoc_per_container": "10.00",
            "containers-1-container_numbers": "MSCU002",
            "containers-2-quantity": "1",
            "containers-2-container_size": "40ft_hc",
            "containers-2-rate_per_container": "1800.00",
            "containers-2-pvoc_per_container": "20.00",
            "containers-2-container_numbers": "MSCU003",
        }

    def test_quote_form_includes_air_route_and_excludes_loading_date(self):
        form = QuoteForm()

        self.assertIn("origin", form.fields)
        self.assertIn("destination", form.fields)
        self.assertNotIn("loading_date", form.fields)
        self.assertEqual(
            form.fields["port_of_loading"].widget.attrs["placeholder"], "POL"
        )
        self.assertEqual(
            form.fields["port_of_discharge"].widget.attrs["placeholder"],
            "Destination",
        )

    def test_air_cargo_quote_create_needs_no_retired_shipment_fields(self):
        response = self.client.post(
            reverse("quote_create"),
            {
                "client": str(self.customer.pk),
                "cargo_type": "air_cargo",
                "flow_type": "lcl",
                "origin": "Guangzhou",
                "destination": "Entebbe",
                "ctns": "12",
                "gross_weight": "245.50",
                "air_rate_basis": "package",
                "rate_per_kg": "18.00",
                "handling_fees": "25.00",
                "currency": "USD",
                "status": "draft",
            },
        )

        self.assertEqual(response.status_code, 302)
        quote = Quote.objects.get()
        self.assertEqual(quote.origin, "Guangzhou")
        self.assertEqual(quote.destination, "Entebbe")
        self.assertEqual(quote.ctns, 12)
        self.assertEqual(quote.gross_weight, Decimal("245.50"))
        self.assertEqual(quote.item_number, "")
        self.assertEqual(quote.item_description, "")
        self.assertEqual(quote.airline, "")
        self.assertEqual(quote.awb_number, "")
        self.assertEqual(quote.commodity, "")
        self.assertIsNone(quote.flight_date)
        self.assertIsNone(quote.estimated_arrival)

    def test_fcl_row_uses_simple_container_input_and_pvoc_field(self):
        formset = QuoteContainerFormSet(prefix="containers")
        form = formset.empty_form

        self.assertEqual(form.fields["container_numbers"].widget.input_type, "text")
        self.assertIn("pvoc_per_container", form.fields)
        self.assertEqual(form.fields["quantity"].max_value, 1)
        self.assertTrue(form.fields["quantity"].widget.is_hidden)

    def test_invoice_conversion_excludes_route_fields_and_fcl_cbm(self):
        quote = Quote(cargo_type="freight_cargo", flow_type="fcl")
        form = QuoteInvoiceConversionForm(quote=quote, uses_container_lines=True)

        for field_name in (
            "loading_date",
            "origin",
            "destination",
            "final_destination",
            "vessel_voyage",
            "etd",
            "eta",
            "measurement",
            "incoterm",
        ):
            self.assertNotIn(field_name, form.fields)
        self.assertEqual(form.fields["port_of_loading"].label, "POL")
        self.assertEqual(form.fields["port_of_discharge"].label, "Destination")
        self.assertEqual(
            form.fields["port_of_discharge"].widget.attrs["placeholder"],
            "Destination",
        )

    def test_invoice_conversion_retains_cbm_for_lcl_only(self):
        quote = Quote(cargo_type="freight_cargo", flow_type="lcl")
        form = QuoteInvoiceConversionForm(quote=quote)

        self.assertIn("measurement", form.fields)
        self.assertNotIn("container_number", form.fields)
        self.assertNotIn("container_size", form.fields)

    def test_air_cargo_invoice_conversion_form_omits_freight_fields(self):
        quote = Quote(cargo_type="air_cargo", flow_type="lcl")

        form = QuoteInvoiceConversionForm(quote=quote, uses_container_lines=True)

        self.assertIn("origin", form.fields)
        self.assertIn("destination", form.fields)
        self.assertIn("ctns", form.fields)
        self.assertIn("gross_weight", form.fields)
        self.assertNotIn("item_number", form.fields)
        self.assertNotIn("item_description", form.fields)
        self.assertNotIn("cargo_unit", form.fields)
        self.assertNotIn("airline", form.fields)
        self.assertNotIn("measurement", form.fields)
        self.assertNotIn("container_number", form.fields)
        self.assertNotIn("container_size", form.fields)
        self.assertNotIn("port_of_loading", form.fields)
        self.assertNotIn("port_of_discharge", form.fields)

    @override_settings(
        STORAGES={
            "default": {
                "BACKEND": "django.core.files.storage.FileSystemStorage",
            },
            "staticfiles": {
                "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
            },
        }
    )
    def test_air_cargo_invoice_conversion_page_loads(self):
        quote = Quote.objects.create(
            client=self.customer,
            cargo_type="air_cargo",
            flow_type="lcl",
            status="accepted",
            created_by=self.user,
        )

        response = self.client.get(reverse("quote_convert_to_invoice", args=[quote.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Air Cargo Details")

    @override_settings(
        STORAGES={
            "default": {
                "BACKEND": "django.core.files.storage.FileSystemStorage",
            },
            "staticfiles": {
                "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
            },
        }
    )
    def test_air_cargo_conversion_saves_only_current_shipment_details(self):
        quote = Quote.objects.create(
            client=self.customer,
            cargo_type="air_cargo",
            flow_type="lcl",
            status="accepted",
            item_number="OLD-ITEM",
            item_description="Old description",
            airline="Old Airline",
            awb_number="OLD-AWB",
            flight_date=timezone.now(),
            estimated_arrival=timezone.now(),
            commodity="Old commodity",
            created_by=self.user,
        )

        response = self.client.post(
            reverse("quote_convert_to_invoice", args=[quote.pk]),
            {
                "origin": "Guangzhou",
                "destination": "Entebbe",
                "ctns": "12",
                "gross_weight": "245.50",
                "air_rate_basis": "package",
                "rate_per_kg": "18.00",
                "handling_fees": "25.00",
                "currency": "USD",
            },
        )

        self.assertEqual(response.status_code, 302)
        quote.refresh_from_db()
        loading = quote.loading
        self.assertEqual(quote.origin, "Guangzhou")
        self.assertEqual(quote.destination, "Entebbe")
        self.assertEqual(quote.ctns, 12)
        self.assertEqual(quote.gross_weight, Decimal("245.50"))
        self.assertEqual(loading.origin, "Guangzhou")
        self.assertEqual(loading.destination, "Entebbe")
        self.assertEqual(loading.ctns, 12)
        self.assertEqual(loading.gross_weight, Decimal("245.50"))
        for value in (
            quote.item_number,
            quote.item_description,
            quote.airline,
            quote.awb_number,
            quote.commodity,
            loading.item_number,
            loading.item_description,
            loading.airline,
            loading.awb_number,
            loading.commodity,
        ):
            self.assertEqual(value, "")
        self.assertIsNone(quote.flight_date)
        self.assertIsNone(quote.estimated_arrival)
        self.assertIsNone(loading.flight_date)
        self.assertIsNone(loading.estimated_arrival)

        payment = Payment.objects.get(loading=loading)
        pdf_response = self.client.get(reverse("payment_invoice", args=[payment.pk]))
        self.assertEqual(pdf_response.status_code, 200)
        self.assertEqual(pdf_response["Content-Type"], "application/pdf")

    def test_paid_invoice_and_receipt_draw_their_respective_stamps(self):
        loading = Loading.objects.create(
            client=self.customer,
            cargo_type="freight_cargo",
            flow_type="lcl",
            loading_date=timezone.now(),
            origin="Mombasa",
            destination="Kampala",
            weight=Decimal("1.00"),
            created_by=self.user,
        )
        payment = Payment.objects.create(
            loading=loading,
            rate_per_cbm=Decimal("100.00"),
            amount_charged=Decimal("100.00"),
            amount_paid=0,
            balance=Decimal("100.00"),
            created_by=self.user,
        )

        with patch("logistics.views._draw_invoice_paid_stamp") as draw_invoice_stamp:
            response = self.client.get(reverse("payment_invoice", args=[payment.pk]))
            self.assertEqual(response.status_code, 200)
            draw_invoice_stamp.assert_not_called()

        first_transaction = PaymentTransaction.objects.create(
            payment=payment,
            amount=Decimal("40.00"),
            payment_method="cash",
            received_by="Amina N.",
            reference="BANK-REF-040",
            verification_status="approved",
            created_by=self.user,
        )
        payment.refresh_from_db()
        self.assertEqual(payment.balance, Decimal("60.00"))

        with patch(
            "logistics.views.PaymentVerificationStamp",
            wraps=PaymentVerificationStamp,
        ) as receipt_stamp:
            response = self.client.get(
                reverse("payment_receipt", args=[first_transaction.pk])
            )
            self.assertEqual(response.status_code, 200)
            self.assertFalse(receipt_stamp.call_args.kwargs["fully_paid"])
            self.assertEqual(
                receipt_stamp.call_args.kwargs["receipt_number"],
                first_transaction.receipt_number,
            )
            self.assertEqual(
                receipt_stamp.call_args.kwargs["invoice_number"],
                payment.invoice_number,
            )
            first_rotation = receipt_stamp.call_args.kwargs["rotation_degrees"]
            self.assertGreaterEqual(first_rotation, -4.5)
            self.assertLessEqual(first_rotation, 4.5)

        with patch(
            "logistics.views.PaymentVerificationStamp",
            wraps=PaymentVerificationStamp,
        ) as receipt_stamp:
            self.client.get(reverse("payment_receipt", args=[first_transaction.pk]))
            self.assertEqual(
                receipt_stamp.call_args.kwargs["rotation_degrees"],
                first_rotation,
            )

        with patch("logistics.views._draw_invoice_paid_stamp") as draw_invoice_stamp:
            response = self.client.get(reverse("payment_invoice", args=[payment.pk]))
            self.assertEqual(response.status_code, 200)
            draw_invoice_stamp.assert_called()
            self.assertEqual(draw_invoice_stamp.call_args.args[2].pk, payment.pk)
            self.assertEqual(
                [item.pk for item in draw_invoice_stamp.call_args.args[3]],
                [first_transaction.pk],
            )

        second_transaction = PaymentTransaction.objects.create(
            payment=payment,
            amount=Decimal("70.00"),
            payment_method="cash",
            received_by="Amina N.",
            reference="BANK-REF-070",
            verification_status="approved",
            created_by=self.user,
        )
        payment.refresh_from_db()
        self.assertEqual(payment.amount_paid, Decimal("110.00"))
        self.assertEqual(payment.balance, Decimal("-10.00"))

        with patch("logistics.views._draw_invoice_paid_stamp") as draw_invoice_stamp:
            response = self.client.get(reverse("payment_invoice", args=[payment.pk]))
            self.assertEqual(response.status_code, 200)
            draw_invoice_stamp.assert_called()
            self.assertEqual(
                [item.pk for item in draw_invoice_stamp.call_args.args[3]],
                [first_transaction.pk, second_transaction.pk],
            )

        with patch(
            "logistics.views.PaymentVerificationStamp",
            wraps=PaymentVerificationStamp,
        ) as receipt_stamp:
            response = self.client.get(
                reverse("payment_receipt", args=[second_transaction.pk])
            )
            self.assertEqual(response.status_code, 200)
            self.assertTrue(receipt_stamp.call_args.kwargs["fully_paid"])
            self.assertEqual(
                receipt_stamp.call_args.kwargs["receipt_number"],
                second_transaction.receipt_number,
            )
            second_rotation = receipt_stamp.call_args.kwargs["rotation_degrees"]
            self.assertGreaterEqual(second_rotation, -4.5)
            self.assertLessEqual(second_rotation, 4.5)
            self.assertNotEqual(second_rotation, first_rotation)

        pdf_response = self.client.get(reverse("payment_invoice", args=[payment.pk]))
        self.assertEqual(pdf_response.status_code, 200)
        self.assertEqual(pdf_response["Content-Type"], "application/pdf")

        receipt_response = self.client.get(
            reverse("payment_receipt", args=[second_transaction.pk])
        )
        self.assertEqual(receipt_response.status_code, 200)
        self.assertEqual(receipt_response["Content-Type"], "application/pdf")

    def test_payment_receiver_is_required(self):
        form = PaymentTransactionForm(
            data={
                "amount": "100.00",
                "payment_date": "2026-08-28T10:30",
                "payment_method": "cash",
                "received_by": "",
                "reference": "CASH-100",
                "notes": "",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("received_by", form.errors)

    def test_quote_create_saves_mixed_fcl_rows_and_total(self):
        data = {
            "client": str(self.customer.pk),
            "cargo_type": "freight_cargo",
            "flow_type": "fcl",
            "port_of_loading": "Mombasa",
            "port_of_discharge": "Kampala",
            "origin": "Mombasa",
            "destination": "Kampala",
            "currency": "USD",
            "document_handling_fee": "50.00",
            "status": "draft",
            **self._container_management_data(),
        }

        response = self.client.post(reverse("quote_create"), data)

        self.assertEqual(response.status_code, 302)
        quote = Quote.objects.get()
        self.assertEqual(quote.container_lines.count(), 3)
        self.assertEqual(quote.amount_quoted, Decimal("3890.00"))
        self.assertEqual(quote.container_lines.first().total_amount, Decimal("1010.00"))
        self.assertEqual(quote.container_size, "20ft")
        self.assertNotIn(
            "dry", quote.container_lines.first().get_container_size_display().lower()
        )
        pdf_response = self.client.get(reverse("quote_pdf", args=[quote.pk]))
        self.assertEqual(pdf_response.status_code, 200)
        self.assertEqual(pdf_response["Content-Type"], "application/pdf")

    def test_quote_create_rejects_missing_container_number(self):
        container_data = self._container_management_data()
        container_data["containers-0-container_numbers"] = ""
        formset = QuoteContainerFormSet(
            data=container_data,
            instance=Quote(client=self.customer, created_by=self.user),
            prefix="containers",
        )

        self.assertFalse(formset.is_valid())
        self.assertIn(
            "This field is required.", formset.forms[0].errors["container_numbers"]
        )

    def test_conversion_copies_mixed_fcl_rows_to_one_invoice(self):
        quote = Quote.objects.create(
            client=self.customer,
            cargo_type="freight_cargo",
            flow_type="fcl",
            origin="Mombasa",
            destination="Kampala",
            document_handling_fee=Decimal("50.00"),
            status="accepted",
            created_by=self.user,
        )
        conversion_data = {
            "currency": "USD",
            "port_of_loading": "Mombasa",
            "port_of_discharge": "Kampala",
            "document_handling_fee": "50.00",
            "pvoc_fee": "25.00",
            **self._container_management_data(),
        }

        response = self.client.post(
            reverse("quote_convert_to_invoice", args=[quote.pk]), conversion_data
        )

        self.assertEqual(response.status_code, 302)
        quote.refresh_from_db()
        payment = Payment.objects.get(loading=quote.loading)
        self.assertEqual(quote.port_of_loading, "Mombasa")
        self.assertEqual(quote.port_of_discharge, "Kampala")
        self.assertEqual(payment.loading.port_of_loading, "Mombasa")
        self.assertEqual(payment.loading.port_of_discharge, "Kampala")
        self.assertEqual(payment.loading.container_lines.count(), 3)
        self.assertEqual(payment.amount_charged, Decimal("3890.00"))
        self.assertEqual(payment.pvoc_total, Decimal("40.00"))
        self.assertEqual(
            payment.loading.container_lines.first().total_amount,
            Decimal("1010.00"),
        )
        self.assertEqual(
            payment.loading.container_lines.last().container_size, "40ft_hc"
        )
        pdf_response = self.client.get(reverse("payment_invoice", args=[payment.pk]))
        self.assertEqual(pdf_response.status_code, 200)
        self.assertEqual(pdf_response["Content-Type"], "application/pdf")

    def test_loading_create_can_save_mixed_fcl_and_create_one_invoice(self):
        data = {
            "client": str(self.customer.pk),
            "cargo_type": "freight_cargo",
            "flow_type": "fcl",
            "port_of_loading": "Mombasa",
            "port_of_discharge": "Kampala",
            "loading_date": timezone.now().strftime("%Y-%m-%dT%H:%M"),
            "origin": "Mombasa",
            "destination": "Kampala",
            "currency": "USD",
            "create_invoice": "1",
            **self._container_management_data(),
        }

        response = self.client.post(reverse("loading_create"), data)

        self.assertEqual(response.status_code, 302)
        loading = Loading.objects.get()
        self.assertEqual(loading.container_lines.count(), 3)
        self.assertEqual(loading.fcl_container_count, 3)
        self.assertEqual(loading.fcl_freight_total, Decimal("3800.00"))
        payment = Payment.objects.get(loading=loading)
        self.assertEqual(payment.amount_charged, Decimal("3840.00"))
        self.assertEqual(payment.pvoc_total, Decimal("40.00"))
        self.assertEqual(response.url, reverse("payment_detail", args=[payment.pk]))

    def test_saved_mixed_fcl_can_be_invoiced_without_single_rate(self):
        loading = Loading.objects.create(
            client=self.customer,
            cargo_type="freight_cargo",
            flow_type="fcl",
            loading_date=timezone.now(),
            origin="Mombasa",
            destination="Kampala",
            created_by=self.user,
        )
        loading.container_lines.create(
            quantity=2,
            container_size="20ft",
            rate_per_container=Decimal("1000.00"),
            container_numbers="MSCU001, MSCU002",
        )
        loading.container_lines.create(
            quantity=1,
            container_size="40ft_hc",
            rate_per_container=Decimal("1800.00"),
            container_numbers="MSCU003",
        )

        response = self.client.post(
            reverse("payment_create_with_loading", args=[loading.pk]),
            {
                "loading": str(loading.pk),
                "document_handling_fee": "50.00",
                "pvoc_fee": "25.00",
            },
        )

        self.assertEqual(response.status_code, 302)
        payment = Payment.objects.get(loading=loading)
        self.assertEqual(payment.amount_charged, Decimal("3925.00"))
