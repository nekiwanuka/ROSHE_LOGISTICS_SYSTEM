import random
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import CommandError
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from logistics.models import (
    Client,
    ContainerReturn,
    Loading,
    Payment,
    PaymentTransaction,
    Quote,
    Transit,
)


class Command(BaseCommand):
    help = "Seed sample data for ROSHE LOGISTICS (clients, cargo, transits, payments, quotations, container returns)."

    def add_arguments(self, parser):
        parser.add_argument("--clients", type=int, default=5)
        parser.add_argument("--loadings", type=int, default=15)
        parser.add_argument("--transits", type=int, default=8)
        parser.add_argument("--payments", type=int, default=12)
        parser.add_argument("--transactions", type=int, default=18)
        parser.add_argument("--quotes", type=int, default=10)
        parser.add_argument("--container-returns", type=int, default=6)
        parser.add_argument(
            "--created-by",
            type=str,
            default=None,
            help="Username of an existing user to own seeded records. If not provided, uses/creates seed_admin.",
        )
        parser.add_argument(
            "--allow-create-user",
            action="store_true",
            help="If --created-by is provided but does not exist, create it as a superuser seed account.",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Delete existing sample data created by this command.",
        )
        parser.add_argument("--dry-run", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        clear = options["clear"]

        if clear:
            self._clear_sample_data(dry_run=dry_run)
            return

        created_by = self._get_or_create_seed_user(
            username=options.get("created_by"),
            allow_create=bool(options.get("allow_create_user")),
        )

        clients = self._create_clients(count=options["clients"], created_by=created_by)
        loadings = self._create_loadings(
            count=options["loadings"], clients=clients, created_by=created_by
        )
        transits = self._create_transits(
            count=options["transits"], loadings=loadings, created_by=created_by
        )
        quotes = self._create_quotes(
            count=options["quotes"], clients=clients, created_by=created_by
        )
        payments = self._create_payments(
            count=options["payments"], loadings=loadings, created_by=created_by
        )
        self._create_transactions(
            count=options["transactions"], payments=payments, created_by=created_by
        )
        container_returns = self._create_container_returns(
            count=options["container_returns"],
            loadings=loadings,
            created_by=created_by,
        )

        if dry_run:
            raise transaction.TransactionManagementError(
                "Dry-run: rolling back transaction"
            )

        self.stdout.write(self.style.SUCCESS("Sample data created successfully."))
        self.stdout.write(
            f"Created: {len(clients)} clients, {len(loadings)} cargo/loadings, {len(transits)} transits, {len(quotes)} quotations, {len(payments)} payments, {len(container_returns)} container returns"
        )

    def _create_quotes(self, count, clients, created_by):
        if count <= 0:
            return []

        origins = ["China - Guangzhou", "China - Yiwu", "UAE - Dubai"]
        destinations = ["Kampala", "Mombasa"]
        item_descriptions = [
            "[SAMPLE_DATA] Electronics and accessories",
            "[SAMPLE_DATA] Boutique garments",
            "[SAMPLE_DATA] Spare parts",
            "[SAMPLE_DATA] Household merchandise",
        ]
        airlines = ["Emirates SkyCargo", "Ethiopian Cargo", "Qatar Airways Cargo"]
        units = ["ctn", "package", "parcel", "pack", "set"]
        statuses = ["draft", "sent", "accepted"]

        created = []
        now = timezone.now()
        for i in range(count):
            cargo_type = "air_cargo" if i % 4 == 0 else "freight_cargo"
            flow_type = (
                "lcl" if cargo_type == "air_cargo" else ("fcl" if i % 2 == 0 else "lcl")
            )
            client = random.choice(clients)
            origin = random.choice(origins)
            destination = random.choice(destinations)
            loading_date = now - timezone.timedelta(days=random.randint(1, 90))
            status = random.choice(statuses)
            fee = Decimal("0.00") if i % 3 else Decimal("25.00")
            item_description = random.choice(item_descriptions)

            if cargo_type == "air_cargo":
                cbm = None
                rate_cbm = None
                rate_container = None
                container_size = None
                document_fee = Decimal("0.00")
                pvoc_fee = Decimal("0.00")
                gross_weight = Decimal(str(round(random.uniform(40.0, 450.0), 2)))
                cargo_unit = random.choice(units)
                air_rate_basis = "kg" if i % 8 == 0 else "package"
                rate_per_kg = Decimal(str(round(random.uniform(3.5, 8.5), 2)))
                handling_fees = fee or Decimal("35.00")
                item_number = f"AIR-{now:%y%m}-{i + 1:03d}"
                ctns = random.randint(3, 60)
                airline = random.choice(airlines)
                size_per_carton = random.choice(
                    ["45x35x30 cm", "60x40x40 cm", "Assorted cartons"]
                )
                awb_number = f"784-{random.randint(10000000, 99999999)}"
            elif flow_type == "lcl":
                cbm = Decimal(str(round(random.uniform(1.0, 30.0), 2)))
                rate_cbm = Decimal(str(round(random.uniform(60, 120), 2)))
                rate_container = None
                container_size = None
                document_fee = fee
                pvoc_fee = Decimal("0.00")
                gross_weight = None
                cargo_unit = "ctn"
                air_rate_basis = "package"
                rate_per_kg = None
                handling_fees = Decimal("0.00")
                item_number = ""
                ctns = None
                airline = ""
                size_per_carton = ""
                awb_number = ""
            else:
                cbm = None
                rate_cbm = None
                rate_container = Decimal(str(round(random.uniform(900, 1800), 2)))
                container_size = ""
                document_fee = fee
                pvoc_fee = Decimal("0.00")
                gross_weight = None
                cargo_unit = "set"
                air_rate_basis = "package"
                rate_per_kg = None
                handling_fees = Decimal("0.00")
                item_number = ""
                ctns = None
                airline = ""
                size_per_carton = ""
                awb_number = ""

            quote = Quote.objects.create(
                client=client,
                cargo_type=cargo_type,
                flow_type=flow_type,
                container_number="",
                container_size=container_size,
                origin=origin,
                destination=destination,
                loading_date=loading_date,
                item_number=item_number,
                item_description=item_description,
                ctns=ctns,
                gross_weight=gross_weight,
                cargo_unit=cargo_unit,
                air_rate_basis=air_rate_basis,
                rate_per_kg=rate_per_kg,
                handling_fees=handling_fees,
                airline=airline,
                size_per_carton=size_per_carton,
                payment_terms=(
                    "100% Before Delivery"
                    if cargo_type == "air_cargo"
                    else "100% Before Shipment"
                ),
                currency="USD",
                incoterm="",
                port_of_loading="",
                port_of_discharge="",
                final_destination="",
                vessel_voyage="",
                etd=None,
                eta=None,
                seal_number="",
                no_of_packages="",
                measurement=None,
                awb_number=awb_number,
                flight_date=loading_date if cargo_type == "air_cargo" else None,
                estimated_arrival=(
                    loading_date + timezone.timedelta(days=3)
                    if cargo_type == "air_cargo"
                    else None
                ),
                commodity=item_description.replace("[SAMPLE_DATA] ", ""),
                cbm=cbm,
                rate_per_cbm=rate_cbm,
                rate_per_container=rate_container,
                document_handling_fee=document_fee,
                pvoc_fee=pvoc_fee,
                status=status,
                notes="[SAMPLE_DATA] seeded",
                created_by=created_by,
            )
            created.append(quote)
        return created

    def _get_or_create_seed_user(self, username=None, allow_create=False):
        User = get_user_model()

        if username:
            user = User.objects.filter(username=username).first()
            if not user:
                if not allow_create:
                    raise CommandError(
                        f"User '{username}' does not exist. Create it first, or pass --allow-create-user."
                    )
                user = User.objects.create(
                    username=username,
                    email=f"{username}@example.com",
                    first_name="Seed",
                    last_name="Admin",
                    role="superuser",
                    is_staff=True,
                    is_superuser=True,
                )
        else:
            user, _ = User.objects.get_or_create(
                username="seed_admin",
                defaults={
                    "email": "seed_admin@example.com",
                    "first_name": "Seed",
                    "last_name": "Admin",
                    "role": "superuser",
                    "is_staff": True,
                    "is_superuser": True,
                },
            )

        if not user.has_usable_password():
            user.set_password("seed_admin_123")
            user.save(update_fields=["password"])
        return user

    def _create_clients(self, count, created_by):
        names = [
            ("Kampala Traders", "Sarah N.", "+256 700 111111"),
            ("East Africa Imports", "James K.", "+256 701 222222"),
            ("Mombasa Supplies", "Amina A.", "+254 711 333333"),
            ("Roshe Partner Co", "Brian M.", "+256 702 444444"),
            ("Global Freight Buyers", "Fatima S.", "+256 703 555555"),
            ("Golden Mart", "Paul T.", "+256 704 666666"),
            ("KGL Wholesale", "Grace L.", "+256 705 777777"),
        ]
        random.shuffle(names)
        created = []
        for i in range(count):
            company, contact, phone = names[i % len(names)]
            client = Client.objects.create(
                name=company,
                company_name=company,
                contact_person=contact,
                phone=phone,
                email=f"client{i+1}@example.com",
                country="Uganda",
                address="Plot 13 Mukwano Courts, Buganda Road, Kampala",
                remarks="[SAMPLE_DATA] seeded",
                created_by=created_by,
            )
            created.append(client)
        return created

    def _create_loadings(self, count, clients, created_by):
        origins = ["China - Guangzhou", "China - Yiwu", "UAE - Dubai"]
        destinations = ["Kampala", "Mombasa"]
        container_numbers = [
            "MSCU1234567",
            "TLLU7654321",
            "SUDU5794345",
            "OOLU9988776",
            "CMAU1122334",
        ]
        units = ["ctn", "package", "parcel", "pack", "set"]
        created = []
        now = timezone.now()
        for i in range(count):
            cargo_type = "air_cargo" if i % 5 == 0 else "freight_cargo"
            flow_type = (
                "lcl" if cargo_type == "air_cargo" else ("fcl" if i % 2 == 0 else "lcl")
            )
            client = random.choice(clients)
            origin = random.choice(origins)
            destination = random.choice(destinations)
            loading_date = now - timezone.timedelta(days=random.randint(1, 120))

            if cargo_type == "air_cargo":
                container_number = ""
                container_size = ""
                cbm = None
                item_number = f"AIR-CARGO-{i + 1:03d}"
                item_description = "[SAMPLE_DATA] Air cargo merchandise"
                ctns = random.randint(5, 80)
                gross_weight = Decimal(str(round(random.uniform(35.0, 500.0), 2)))
                cargo_unit = random.choice(units)
                air_rate_basis = "kg" if i % 10 == 0 else "package"
                rate_per_kg = Decimal(str(round(random.uniform(3.5, 8.5), 2)))
                handling_fees = Decimal(str(round(random.uniform(20.0, 75.0), 2)))
                airline = random.choice(
                    ["Emirates SkyCargo", "Ethiopian Cargo", "Qatar Airways Cargo"]
                )
                size_per_carton = random.choice(
                    ["45x35x30 cm", "60x40x40 cm", "Assorted cartons"]
                )
                no_of_packages = str(ctns)
                measurement = None
            elif flow_type == "fcl":
                container_number = random.choice(container_numbers) + str(i % 10)
                container_size = random.choice(["20ft", "40ft"])
                cbm = None
                item_number = ""
                item_description = "[SAMPLE_DATA] Full container goods"
                ctns = None
                gross_weight = None
                cargo_unit = "set"
                air_rate_basis = "package"
                rate_per_kg = None
                handling_fees = Decimal("0.00")
                airline = ""
                size_per_carton = ""
                no_of_packages = f"{random.randint(80, 260)} Packages"
                measurement = Decimal(str(round(random.uniform(20.0, 65.0), 2)))
            else:
                container_number = random.choice(container_numbers) + str(i % 10)
                container_size = ""
                cbm = Decimal(str(round(random.uniform(1.0, 30.0), 2)))
                item_number = ""
                item_description = "[SAMPLE_DATA] LCL consolidated goods"
                ctns = None
                gross_weight = None
                cargo_unit = "ctn"
                air_rate_basis = "package"
                rate_per_kg = None
                handling_fees = Decimal("0.00")
                airline = ""
                size_per_carton = ""
                no_of_packages = f"{random.randint(10, 180)} CTN"
                measurement = cbm

            loading = Loading.objects.create(
                flow_type=flow_type,
                cargo_type=cargo_type,
                client=client,
                loading_date=loading_date,
                item_number=item_number,
                item_description=item_description,
                ctns=ctns,
                weight=cbm,
                gross_weight=gross_weight,
                cargo_unit=cargo_unit,
                air_rate_basis=air_rate_basis,
                rate_per_kg=rate_per_kg,
                handling_fees=handling_fees,
                airline=airline,
                size_per_carton=size_per_carton,
                payment_terms=(
                    "100% Before Delivery"
                    if cargo_type == "air_cargo"
                    else "100% Before Shipment"
                ),
                currency="USD",
                incoterm="" if cargo_type == "air_cargo" else "FOB Guangzhou, China",
                port_of_loading=origin if cargo_type == "freight_cargo" else "",
                port_of_discharge=(
                    "Mombasa, Kenya" if cargo_type == "freight_cargo" else ""
                ),
                final_destination=destination,
                vessel_voyage=(
                    random.choice(
                        ["COSCO SHIPPING / 123S", "MSC / 908E", "MAERSK / 442W"]
                    )
                    if cargo_type == "freight_cargo"
                    else ""
                ),
                etd=loading_date if cargo_type == "freight_cargo" else None,
                eta=(
                    loading_date + timezone.timedelta(days=14)
                    if cargo_type == "freight_cargo"
                    else None
                ),
                seal_number="TBC" if cargo_type == "freight_cargo" else "",
                no_of_packages=no_of_packages,
                measurement=measurement,
                awb_number=(
                    f"784-{random.randint(10000000, 99999999)}"
                    if cargo_type == "air_cargo"
                    else ""
                ),
                flight_date=loading_date if cargo_type == "air_cargo" else None,
                estimated_arrival=(
                    loading_date + timezone.timedelta(days=3)
                    if cargo_type == "air_cargo"
                    else None
                ),
                commodity=item_description.replace("[SAMPLE_DATA] ", ""),
                container_number=container_number,
                container_size=container_size,
                origin=origin,
                destination=destination,
                created_by=created_by,
            )
            created.append(loading)
        return created

    def _create_transits(self, count, loadings, created_by):
        shipping_lines = ["MSC", "MAERSK", "CMA CGM", "Hapag-Lloyd"]
        statuses = ["awaiting", "in_transit", "arrived"]
        created = []
        now = timezone.now()

        # link by container_number (your system matches transit to cargo by container number)
        candidates = [l for l in loadings if l.container_number]
        random.shuffle(candidates)
        for i in range(min(count, len(candidates))):
            loading = candidates[i]
            boarding = now - timezone.timedelta(days=random.randint(5, 60))
            eta = boarding + timezone.timedelta(days=random.randint(7, 35))
            transit = Transit.objects.create(
                shipping_line=random.choice(shipping_lines),
                container_number=loading.container_number,
                boarding_date=boarding,
                eta_location=random.choice(["kampala", "mombasa"]),
                eta=eta,
                status=random.choice(statuses),
                remarks="[SAMPLE_DATA] seeded",
                created_by=created_by,
            )
            created.append(transit)
        return created

    def _create_payments(self, count, loadings, created_by):
        methods = ["cash", "bank", "mobile_money", "cheque"]
        created = []

        candidates = list(loadings)
        random.shuffle(candidates)
        for i in range(min(count, len(candidates))):
            loading = candidates[i]
            method = random.choice(methods)
            fee = Decimal("0.00") if i % 3 else Decimal("25.00")

            if loading.cargo_type == "air_cargo":
                rate_cbm = None
                rate_container = None
                document_fee = loading.handling_fees or Decimal("0.00")
                pvoc_fee = Decimal("0.00")
            elif loading.flow_type == "lcl":
                rate_cbm = Decimal(str(round(random.uniform(60, 120), 2)))
                rate_container = None
                document_fee = fee
                pvoc_rate = (
                    Decimal(str(round(random.uniform(1.0, 4.0), 2)))
                    if i % 2
                    else Decimal("0.00")
                )
                pvoc_fee = pvoc_rate
            else:
                rate_cbm = None
                rate_container = Decimal(str(round(random.uniform(900, 1800), 2)))
                document_fee = fee
                pvoc_fee = (
                    Decimal(str(round(random.uniform(15.0, 45.0), 2)))
                    if i % 2 == 0
                    else Decimal("0.00")
                )

            payment, _ = Payment.objects.get_or_create(
                loading=loading,
                defaults={
                    "rate_per_cbm": rate_cbm,
                    "rate_per_container": rate_container,
                    "document_handling_fee": document_fee,
                    "pvoc_fee": pvoc_fee,
                    "amount_charged": Decimal("0.00"),
                    "amount_paid": Decimal("0.00"),
                    "balance": Decimal("0.00"),
                    "payment_date": None,
                    "payment_method": method,
                    "receipt_number": "",
                    "created_by": created_by,
                },
            )
            # ensure totals computed
            payment.save()
            created.append(payment)
        return created

    def _create_transactions(self, count, payments, created_by):
        if not payments:
            return

        methods = ["cash", "bank", "mobile_money", "cheque"]
        for i in range(count):
            payment = random.choice(payments)
            if payment.amount_charged <= 0:
                continue

            # pay up to 80% per transaction
            max_pay = float(payment.amount_charged) * 0.8
            amount = Decimal(str(round(random.uniform(10.0, max(10.0, max_pay)), 2)))
            PaymentTransaction.objects.create(
                payment=payment,
                amount=amount,
                payment_date=timezone.now()
                - timezone.timedelta(days=random.randint(0, 45)),
                payment_method=random.choice(methods),
                received_by=created_by.get_full_name() or created_by.username,
                reference=f"SAMPLE-{random.randint(100000, 999999)}",
                notes="[SAMPLE_DATA] seeded",
                verification_status="approved" if i % 3 else "pending",
                verification_notes="",
                created_by=created_by,
            )

    def _create_container_returns(self, count, loadings, created_by):
        if not loadings or count <= 0:
            return []

        conditions = ["good", "damaged"]
        statuses = ["returned", "pending", "damaged_inspected"]

        candidates = [l for l in loadings if l.container_number]
        random.shuffle(candidates)
        created = []
        now = timezone.now()

        for loading in candidates[: min(count, len(candidates))]:
            return_date = now - timezone.timedelta(days=random.randint(0, 60))
            condition = random.choice(conditions)
            status = "returned" if condition == "good" else random.choice(statuses)
            size = loading.container_size or ""

            obj = ContainerReturn.objects.create(
                container_number=loading.container_number,
                container_size=size,
                loading=loading,
                return_date=return_date,
                condition=condition,
                status=status,
                remarks="[SAMPLE_DATA] seeded",
                created_by=created_by,
            )
            created.append(obj)
        return created

    def _clear_sample_data(self, dry_run=False):
        # Only remove rows we tagged as sample data
        PaymentTransaction.objects.filter(notes__icontains="[SAMPLE_DATA]").delete()
        Payment.objects.filter(
            loading__item_description__icontains="[SAMPLE_DATA]"
        ).delete()
        Transit.objects.filter(remarks__icontains="[SAMPLE_DATA]").delete()
        ContainerReturn.objects.filter(remarks__icontains="[SAMPLE_DATA]").delete()
        Quote.objects.filter(notes__icontains="[SAMPLE_DATA]").delete()
        Loading.objects.filter(item_description__icontains="[SAMPLE_DATA]").delete()
        Client.objects.filter(remarks__icontains="[SAMPLE_DATA]").delete()

        if dry_run:
            raise transaction.TransactionManagementError(
                "Dry-run: rolling back transaction"
            )

        self.stdout.write(self.style.SUCCESS("Sample data cleared successfully."))
