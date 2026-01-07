import random
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import CommandError
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from logistics.models import Client, ContainerReturn, Loading, Payment, PaymentTransaction, Quote, Transit


class Command(BaseCommand):
    help = "Seed sample data for ROSHE LOGISTICS (clients, cargo, transits, payments, quotations, container returns)."

    def add_arguments(self, parser):
        parser.add_argument('--clients', type=int, default=5)
        parser.add_argument('--loadings', type=int, default=15)
        parser.add_argument('--transits', type=int, default=8)
        parser.add_argument('--payments', type=int, default=12)
        parser.add_argument('--transactions', type=int, default=18)
        parser.add_argument('--quotes', type=int, default=10)
        parser.add_argument('--container-returns', type=int, default=6)
        parser.add_argument(
            '--created-by',
            type=str,
            default=None,
            help='Username of an existing user to own seeded records. If not provided, uses/creates seed_admin.',
        )
        parser.add_argument(
            '--allow-create-user',
            action='store_true',
            help='If --created-by is provided but does not exist, create it as a superuser seed account.',
        )
        parser.add_argument('--clear', action='store_true', help='Delete existing sample data created by this command.')
        parser.add_argument('--dry-run', action='store_true')

    @transaction.atomic
    def handle(self, *args, **options):
        dry_run = options['dry_run']
        clear = options['clear']

        if clear:
            self._clear_sample_data(dry_run=dry_run)
            return

        created_by = self._get_or_create_seed_user(
            username=options.get('created_by'),
            allow_create=bool(options.get('allow_create_user')),
        )

        clients = self._create_clients(count=options['clients'], created_by=created_by)
        loadings = self._create_loadings(count=options['loadings'], clients=clients, created_by=created_by)
        transits = self._create_transits(count=options['transits'], loadings=loadings, created_by=created_by)
        quotes = self._create_quotes(count=options['quotes'], clients=clients, created_by=created_by)
        payments = self._create_payments(count=options['payments'], loadings=loadings, created_by=created_by)
        self._create_transactions(count=options['transactions'], payments=payments, created_by=created_by)
        container_returns = self._create_container_returns(
            count=options['container_returns'],
            loadings=loadings,
            created_by=created_by,
        )

        if dry_run:
            raise transaction.TransactionManagementError('Dry-run: rolling back transaction')

        self.stdout.write(self.style.SUCCESS('Sample data created successfully.'))
        self.stdout.write(
            f"Created: {len(clients)} clients, {len(loadings)} cargo/loadings, {len(transits)} transits, {len(quotes)} quotations, {len(payments)} payments, {len(container_returns)} container returns"
        )

    def _create_quotes(self, count, clients, created_by):
        if count <= 0:
            return []

        origins = ['China - Guangzhou', 'China - Yiwu', 'UAE - Dubai']
        destinations = ['Kampala', 'Mombasa']
        container_numbers = [
            'MSCU1234567',
            'TLLU7654321',
            'SUDU5794345',
            'OOLU9988776',
            'CMAU1122334',
        ]
        statuses = ['draft', 'sent', 'accepted']

        created = []
        now = timezone.now()
        for i in range(count):
            flow_type = 'fcl' if i % 2 == 0 else 'lcl'
            client = random.choice(clients)
            origin = random.choice(origins)
            destination = random.choice(destinations)
            container_number = random.choice(container_numbers) + str((i + 3) % 10)
            loading_date = now - timezone.timedelta(days=random.randint(1, 90))
            status = random.choice(statuses)
            fee = Decimal('0.00') if i % 3 else Decimal('25.00')

            if flow_type == 'lcl':
                cbm = Decimal(str(round(random.uniform(1.0, 30.0), 2)))
                rate_cbm = Decimal(str(round(random.uniform(60, 120), 2)))
                rate_container = None
                container_size = None
            else:
                cbm = None
                rate_cbm = None
                rate_container = Decimal(str(round(random.uniform(900, 1800), 2)))
                container_size = random.choice(['20ft', '40ft'])

            quote = Quote.objects.create(
                client=client,
                flow_type=flow_type,
                container_number=container_number,
                container_size=container_size,
                origin=origin,
                destination=destination,
                loading_date=loading_date,
                item_description='[SAMPLE_DATA] Quoted goods',
                cbm=cbm,
                rate_per_cbm=rate_cbm,
                rate_per_container=rate_container,
                document_handling_fee=fee,
                status=status,
                notes='[SAMPLE_DATA] seeded',
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
                    first_name='Seed',
                    last_name='Admin',
                    role='superuser',
                    is_staff=True,
                    is_superuser=True,
                )
        else:
            user, _ = User.objects.get_or_create(
                username='seed_admin',
                defaults={
                    'email': 'seed_admin@example.com',
                    'first_name': 'Seed',
                    'last_name': 'Admin',
                    'role': 'superuser',
                    'is_staff': True,
                    'is_superuser': True,
                },
            )

        if not user.has_usable_password():
            user.set_password('seed_admin_123')
            user.save(update_fields=['password'])
        return user

    def _create_clients(self, count, created_by):
        names = [
            ('Kampala Traders', 'Sarah N.', '+256 700 111111'),
            ('East Africa Imports', 'James K.', '+256 701 222222'),
            ('Mombasa Supplies', 'Amina A.', '+254 711 333333'),
            ('Roshe Partner Co', 'Brian M.', '+256 702 444444'),
            ('Global Freight Buyers', 'Fatima S.', '+256 703 555555'),
            ('Golden Mart', 'Paul T.', '+256 704 666666'),
            ('KGL Wholesale', 'Grace L.', '+256 705 777777'),
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
                country='Uganda',
                address='Plot 13 Mukwano Courts, Buganda Road, Kampala',
                remarks='[SAMPLE_DATA] seeded',
                created_by=created_by,
            )
            created.append(client)
        return created

    def _create_loadings(self, count, clients, created_by):
        origins = ['China - Guangzhou', 'China - Yiwu', 'UAE - Dubai']
        destinations = ['Kampala', 'Mombasa']
        container_numbers = [
            'MSCU1234567',
            'TLLU7654321',
            'SUDU5794345',
            'OOLU9988776',
            'CMAU1122334',
        ]
        created = []
        now = timezone.now()
        for i in range(count):
            flow_type = 'fcl' if i % 2 == 0 else 'lcl'
            client = random.choice(clients)
            origin = random.choice(origins)
            destination = random.choice(destinations)
            container_number = random.choice(container_numbers) + str(i % 10)
            loading_date = now - timezone.timedelta(days=random.randint(1, 120))

            if flow_type == 'fcl':
                container_size = random.choice(['20ft', '40ft'])
                cbm = None
            else:
                container_size = ''
                cbm = Decimal(str(round(random.uniform(1.0, 30.0), 2)))

            loading = Loading.objects.create(
                flow_type=flow_type,
                client=client,
                loading_date=loading_date,
                item_description='[SAMPLE_DATA] General goods',
                weight=cbm,
                container_number=container_number,
                container_size=container_size,
                origin=origin,
                destination=destination,
                created_by=created_by,
            )
            created.append(loading)
        return created

    def _create_transits(self, count, loadings, created_by):
        shipping_lines = ['MSC', 'MAERSK', 'CMA CGM', 'Hapag-Lloyd']
        statuses = ['awaiting', 'in_transit', 'arrived']
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
                eta_location=random.choice(['kampala', 'mombasa']),
                eta=eta,
                status=random.choice(statuses),
                remarks='[SAMPLE_DATA] seeded',
                created_by=created_by,
            )
            created.append(transit)
        return created

    def _create_payments(self, count, loadings, created_by):
        methods = ['cash', 'bank', 'mobile_money', 'cheque']
        created = []

        candidates = list(loadings)
        random.shuffle(candidates)
        for i in range(min(count, len(candidates))):
            loading = candidates[i]
            method = random.choice(methods)
            fee = Decimal('0.00') if i % 3 else Decimal('25.00')

            if loading.flow_type == 'lcl':
                rate_cbm = Decimal(str(round(random.uniform(60, 120), 2)))
                rate_container = None
            else:
                rate_cbm = None
                rate_container = Decimal(str(round(random.uniform(900, 1800), 2)))

            payment, _ = Payment.objects.get_or_create(
                loading=loading,
                defaults={
                    'rate_per_cbm': rate_cbm,
                    'rate_per_container': rate_container,
                    'document_handling_fee': fee,
                    'amount_charged': Decimal('0.00'),
                    'amount_paid': Decimal('0.00'),
                    'balance': Decimal('0.00'),
                    'payment_date': None,
                    'payment_method': method,
                    'receipt_number': '',
                    'created_by': created_by,
                },
            )
            # ensure totals computed
            payment.save()
            created.append(payment)
        return created

    def _create_transactions(self, count, payments, created_by):
        if not payments:
            return

        methods = ['cash', 'bank', 'mobile_money', 'cheque']
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
                payment_date=timezone.now() - timezone.timedelta(days=random.randint(0, 45)),
                payment_method=random.choice(methods),
                reference=f"SAMPLE-{random.randint(100000, 999999)}",
                notes='[SAMPLE_DATA] seeded',
                verification_status='approved' if i % 3 else 'pending',
                verification_notes='',
                created_by=created_by,
            )

    def _create_container_returns(self, count, loadings, created_by):
        if not loadings or count <= 0:
            return []

        conditions = ['good', 'damaged']
        statuses = ['returned', 'pending', 'damaged_inspected']

        candidates = [l for l in loadings if l.container_number]
        random.shuffle(candidates)
        created = []
        now = timezone.now()

        for loading in candidates[: min(count, len(candidates))]:
            return_date = now - timezone.timedelta(days=random.randint(0, 60))
            condition = random.choice(conditions)
            status = 'returned' if condition == 'good' else random.choice(statuses)
            size = loading.container_size or ''

            obj = ContainerReturn.objects.create(
                container_number=loading.container_number,
                container_size=size,
                loading=loading,
                return_date=return_date,
                condition=condition,
                status=status,
                remarks='[SAMPLE_DATA] seeded',
                created_by=created_by,
            )
            created.append(obj)
        return created

    def _clear_sample_data(self, dry_run=False):
        # Only remove rows we tagged as sample data
        PaymentTransaction.objects.filter(notes__icontains='[SAMPLE_DATA]').delete()
        Payment.objects.filter(loading__item_description__icontains='[SAMPLE_DATA]').delete()
        Transit.objects.filter(remarks__icontains='[SAMPLE_DATA]').delete()
        ContainerReturn.objects.filter(remarks__icontains='[SAMPLE_DATA]').delete()
        Quote.objects.filter(notes__icontains='[SAMPLE_DATA]').delete()
        Loading.objects.filter(item_description__icontains='[SAMPLE_DATA]').delete()
        Client.objects.filter(remarks__icontains='[SAMPLE_DATA]').delete()

        if dry_run:
            raise transaction.TransactionManagementError('Dry-run: rolling back transaction')

        self.stdout.write(self.style.SUCCESS('Sample data cleared successfully.'))
