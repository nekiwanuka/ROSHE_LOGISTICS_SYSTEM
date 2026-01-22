from django.core.management.base import BaseCommand
from django.db import transaction

from logistics.models import Payment


class Command(BaseCommand):
    help = (
        "Recalculate invoice totals (amount_paid/balance) from approved receipts only. "
        "Use after deploying logic changes or if balances look incorrect."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Compute counts but do not write updates.',
        )
        parser.add_argument(
            '--only-pk',
            type=int,
            default=None,
            help='Recalculate a single Payment by primary key.',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        dry_run = bool(options.get('dry_run'))
        only_pk = options.get('only_pk')

        payments = Payment.objects.all().order_by('pk')
        if only_pk is not None:
            payments = payments.filter(pk=only_pk)

        count = payments.count()
        if count == 0:
            self.stdout.write(self.style.WARNING('No payments found.'))
            return

        for payment in payments:
            payment.refresh_totals()

        if dry_run:
            raise transaction.TransactionManagementError('Dry-run: rolling back transaction')

        self.stdout.write(self.style.SUCCESS(f'Recalculated totals for {count} payment(s).'))
