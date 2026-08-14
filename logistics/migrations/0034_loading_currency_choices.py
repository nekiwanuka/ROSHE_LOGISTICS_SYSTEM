from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("logistics", "0033_document_versions"),
    ]

    operations = [
        migrations.AlterField(
            model_name="loading",
            name="currency",
            field=models.CharField(
                blank=True,
                choices=[
                    ("USD", "USD - US Dollar"),
                    ("UGX", "UGX - Ugandan Shilling"),
                ],
                default="USD",
                max_length=10,
            ),
        ),
    ]
