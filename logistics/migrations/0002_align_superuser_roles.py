from django.db import migrations


def set_superuser_roles(apps, schema_editor):
    CustomUser = apps.get_model('logistics', 'CustomUser')
    CustomUser.objects.filter(is_superuser=True).update(role='superuser', is_staff=True)


def reverse_noop(apps, schema_editor):
    # No reverse operation required because reverting would desync flags again.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('logistics', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(set_superuser_roles, reverse_noop),
    ]
