"""Reprise des adresses des anciennes listes de grm/constants.py dans `NotificationRecipient`, après
confirmation (yes/no). Sans personne pour répondre (déploiement Elastic Beanstalk, tests), rien
n'est importé : lancer ensuite `python manage.py import_notification_recipients`, qui pose la même
question et peut être relancé sans créer de doublon."""
from django.db import migrations


def import_after_confirmation(apps, schema_editor):
    from issue.notification_recipients import (
        IMPORT_COMMAND, ask_yes_no, import_legacy_recipients, is_interactive, legacy_import_question,
    )

    if not is_interactive():
        print(f"\n  Destinataires de notification : import non effectué (pas de confirmation possible). "
              f"Pour l'importer : {IMPORT_COMMAND}")
        return
    if not ask_yes_no('\n  ' + legacy_import_question()):
        print(f"  Import refusé. Il reste possible plus tard : {IMPORT_COMMAND}")
        return
    created, existing = import_legacy_recipients(apps.get_model('issue', 'NotificationRecipient'))
    print(f"  {created} destinataire(s) importé(s), {existing} déjà présent(s).")


class Migration(migrations.Migration):

    dependencies = [
        ('issue', '0015_notificationrecipient'),
    ]

    operations = [
        migrations.RunPython(import_after_confirmation, migrations.RunPython.noop),
    ]
