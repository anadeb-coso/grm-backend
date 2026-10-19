from django.core.management.base import BaseCommand

from issue.models import NotificationRecipient
from issue.notification_recipients import (
    LEGACY_RECIPIENTS, ask_yes_no, import_legacy_recipients, legacy_import_question,
)


class Command(BaseCommand):
    help = (
        "Importe dans la table des destinataires de notification (admin Django) les adresses des "
        "anciennes listes de grm/constants.py, après confirmation (yes/no). Les adresses déjà "
        "présentes ne sont pas modifiées."
    )

    def add_arguments(self, parser):
        parser.add_argument('--yes', action='store_true', help='Importer sans demander de confirmation.')
        parser.add_argument('--dry-run', action='store_true', help="Afficher les adresses sans rien importer.")

    def handle(self, *args, **options):
        labels = dict(NotificationRecipient.GROUP_CHOICES)
        for group, email, role, is_active in LEGACY_RECIPIENTS:
            state = 'active' if is_active else 'inactive'
            self.stdout.write(f'  {str(labels[group]):<35} {email:<35} {role:<15} {state}')
        if options['dry_run']:
            return
        if not options['yes'] and not ask_yes_no(legacy_import_question()):
            self.stdout.write('Import annulé.')
            return
        created, existing = import_legacy_recipients()
        self.stdout.write(self.style.SUCCESS(f'{created} destinataire(s) importé(s), {existing} déjà présent(s).'))
