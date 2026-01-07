from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from logistics.models import (
    AuditLog,
    Client,
    ContainerReturn,
    Loading,
    Payment,
    PaymentTransaction,
    Quote,
    Transit,
)


class Command(BaseCommand):
    help = "Delete all data except users, then recreate seed data."

    def add_arguments(self, parser):
        parser.add_argument('--yes', action='store_true', help='Skip confirmation prompt.')
        parser.add_argument(
            '--created-by',
            type=str,
            default=None,
            help='Username to use as created_by for seeded records (must already exist). Defaults to first superuser.',
        )

        # Forwarded to seed_sample_data
        parser.add_argument('--clients', type=int, default=5)
        parser.add_argument('--loadings', type=int, default=15)
        parser.add_argument('--transits', type=int, default=8)
        parser.add_argument('--payments', type=int, default=12)
        parser.add_argument('--transactions', type=int, default=18)

    @transaction.atomic
    def handle(self, *args, **options):
        if not options['yes']:
            answer = input(
                "This will DELETE all records except users, then reseed sample data. Type YES to continue: "
            )
            if answer.strip() != 'YES':
                self.stdout.write(self.style.WARNING('Cancelled.'))
                return

        created_by_username = options.get('created_by')
        created_by = self._resolve_created_by(created_by_username)

        deleted = self._delete_everything_except_users()
        self.stdout.write(self.style.SUCCESS(f"Deleted non-user data (approx rows): {deleted}"))

        call_command(
            'seed_sample_data',
            clients=options['clients'],
            loadings=options['loadings'],
            transits=options['transits'],
            payments=options['payments'],
            transactions=options['transactions'],
            created_by=created_by.username,
        )

        self.stdout.write(self.style.SUCCESS('Reset + reseed completed.'))

    def _resolve_created_by(self, username=None):
        User = get_user_model()
        if username:
            user = User.objects.filter(username=username).first()
            if not user:
                raise CommandError(
                    f"User '{username}' not found. Create it first or omit --created-by to auto-pick a superuser."
                )
            return user

        user = User.objects.filter(is_superuser=True).order_by('id').first()
        if user:
            return user

        user = User.objects.order_by('id').first()
        if user:
            return user

        raise CommandError('No users exist. Create a superuser first, then rerun this command.')

    def _delete_everything_except_users(self):
        # Delete in dependency order to avoid PROTECT issues.
        total_deleted = 0

        # App data
        total_deleted += PaymentTransaction.objects.all().delete()[0]
        total_deleted += Payment.objects.all().delete()[0]
        total_deleted += Quote.objects.all().delete()[0]
        total_deleted += ContainerReturn.objects.all().delete()[0]
        total_deleted += Transit.objects.all().delete()[0]
        total_deleted += Loading.objects.all().delete()[0]
        total_deleted += Client.objects.all().delete()[0]
        total_deleted += AuditLog.objects.all().delete()[0]

        return total_deleted
