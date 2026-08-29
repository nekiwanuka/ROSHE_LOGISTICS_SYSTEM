from django.db import migrations, models


def backfill_received_by(apps, schema_editor):
    payment_transaction = apps.get_model("logistics", "PaymentTransaction")
    for transaction in payment_transaction.objects.select_related("created_by"):
        created_by = transaction.created_by
        full_name = f"{created_by.first_name} {created_by.last_name}".strip()
        transaction.received_by = full_name or created_by.username
        transaction.save(update_fields=["received_by"])


class Migration(migrations.Migration):
    dependencies = [
        ("logistics", "0038_container_line_pvoc"),
    ]

    operations = [
        migrations.AddField(
            model_name="paymenttransaction",
            name="received_by",
            field=models.CharField(default="", max_length=150),
            preserve_default=False,
        ),
        migrations.RunPython(backfill_received_by, migrations.RunPython.noop),
    ]
