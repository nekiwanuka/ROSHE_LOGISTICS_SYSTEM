from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('logistics', '0020_paymenttransaction_soft_void_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='customuser',
            name='permission_overrides',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
