from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('logistics', '0019_backfill_quote_fields_from_loading'),
    ]

    operations = [
        migrations.AlterField(
            model_name='customuser',
            name='role',
            field=models.CharField(
                choices=[
                    ('superuser', 'Superuser (Admin)'),
                    ('managing_director', 'Managing Director'),
                    ('manager', 'Manager'),
                    ('accountant', 'Accountant'),
                    ('data_entry', 'Front Desk Operator'),
                ],
                default='data_entry',
                max_length=20,
            ),
        ),
    ]
