from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("logistics", "0029_document_shipment_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="loading",
            name="cargo_unit",
            field=models.CharField(
                blank=True,
                choices=[
                    ("kgs", "KGS"),
                    ("ctn", "CTN"),
                    ("package", "Package"),
                    ("set", "Set"),
                ],
                default="kgs",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="quote",
            name="cargo_unit",
            field=models.CharField(
                blank=True,
                choices=[
                    ("kgs", "KGS"),
                    ("ctn", "CTN"),
                    ("package", "Package"),
                    ("set", "Set"),
                ],
                default="kgs",
                max_length=20,
            ),
        ),
    ]
