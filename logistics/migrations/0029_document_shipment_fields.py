from django.db import migrations, models

OPTIONAL_CHAR_FIELDS = [
    ("payment_terms", 100),
    ("currency", 10),
    ("incoterm", 100),
    ("port_of_loading", 255),
    ("port_of_discharge", 255),
    ("final_destination", 255),
    ("vessel_voyage", 255),
    ("seal_number", 100),
    ("no_of_packages", 100),
    ("awb_number", 100),
    ("commodity", 255),
]

OPTIONAL_DATETIME_FIELDS = ["etd", "eta", "flight_date", "estimated_arrival"]
OPTIONAL_DECIMAL_FIELDS = ["measurement", "chargeable_weight"]


class Migration(migrations.Migration):

    dependencies = [
        ("logistics", "0028_quote_pvoc_fee"),
    ]

    operations = []

    for model_name in ("loading", "quote"):
        for field_name, max_length in OPTIONAL_CHAR_FIELDS:
            default = "USD" if field_name == "currency" else ""
            operations.append(
                migrations.AddField(
                    model_name=model_name,
                    name=field_name,
                    field=models.CharField(
                        max_length=max_length, blank=True, default=default
                    ),
                )
            )
        for field_name in OPTIONAL_DATETIME_FIELDS:
            operations.append(
                migrations.AddField(
                    model_name=model_name,
                    name=field_name,
                    field=models.DateTimeField(blank=True, null=True),
                )
            )
        for field_name in OPTIONAL_DECIMAL_FIELDS:
            operations.append(
                migrations.AddField(
                    model_name=model_name,
                    name=field_name,
                    field=models.DecimalField(
                        blank=True, decimal_places=2, max_digits=10, null=True
                    ),
                )
            )
