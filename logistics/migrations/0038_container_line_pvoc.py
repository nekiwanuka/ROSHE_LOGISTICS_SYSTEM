from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("logistics", "0037_require_fcl_container_numbers"),
    ]

    operations = [
        migrations.AddField(
            model_name="loadingcontainerline",
            name="pvoc_per_container",
            field=models.DecimalField(
                blank=True, decimal_places=2, default=0, max_digits=12
            ),
        ),
        migrations.AddField(
            model_name="quotecontainerline",
            name="pvoc_per_container",
            field=models.DecimalField(
                blank=True, decimal_places=2, default=0, max_digits=12
            ),
        ),
    ]
