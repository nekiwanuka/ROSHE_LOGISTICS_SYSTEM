from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("logistics", "0032_loading_air_rate_basis_quote_air_rate_basis"),
    ]

    operations = [
        migrations.AddField(
            model_name="payment",
            name="document_version",
            field=models.CharField(
                choices=[("legacy", "Legacy"), ("current", "Current")],
                default="legacy",
                editable=False,
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="paymenttransaction",
            name="document_version",
            field=models.CharField(
                choices=[("legacy", "Legacy"), ("current", "Current")],
                default="legacy",
                editable=False,
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="quote",
            name="document_version",
            field=models.CharField(
                choices=[("legacy", "Legacy"), ("current", "Current")],
                default="legacy",
                editable=False,
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="payment",
            name="document_version",
            field=models.CharField(
                choices=[("legacy", "Legacy"), ("current", "Current")],
                default="current",
                editable=False,
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="paymenttransaction",
            name="document_version",
            field=models.CharField(
                choices=[("legacy", "Legacy"), ("current", "Current")],
                default="current",
                editable=False,
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="quote",
            name="document_version",
            field=models.CharField(
                choices=[("legacy", "Legacy"), ("current", "Current")],
                default="current",
                editable=False,
                max_length=20,
            ),
        ),
    ]
