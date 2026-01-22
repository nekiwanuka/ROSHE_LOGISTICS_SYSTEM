from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('logistics', '0019_backfill_quote_fields_from_loading'),
    ]

    operations = [
        migrations.AddField(
            model_name='paymenttransaction',
            name='is_voided',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='paymenttransaction',
            name='void_reason',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='paymenttransaction',
            name='voided_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='paymenttransaction',
            name='voided_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='voided_transactions',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
