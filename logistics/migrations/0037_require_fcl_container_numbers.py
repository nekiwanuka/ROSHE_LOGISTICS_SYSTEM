from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("logistics", "0036_quotecontainerline_loadingcontainerline"),
    ]

    operations = [
        migrations.AlterField(
            model_name="loadingcontainerline",
            name="container_numbers",
            field=models.TextField(),
        ),
        migrations.AlterField(
            model_name="quotecontainerline",
            name="container_numbers",
            field=models.TextField(),
        ),
    ]
