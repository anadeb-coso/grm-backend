from django.db import migrations

MANAGER_GROUP = 'InternetCreditManager'


def create_group(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.get_or_create(name=MANAGER_GROUP)


def remove_group(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.filter(name=MANAGER_GROUP, user__isnull=True).delete()


class Migration(migrations.Migration):
    """Groupe optionnel donnant accès à l'espace web « Forfaits internet CVGP » en plus de
    `Admin` et des superusers (internet_credits/permissions.py). Créé vide."""

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
        ('internet_credits', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(create_group, remove_group),
    ]
