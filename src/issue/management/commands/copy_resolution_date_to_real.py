"""Copie `Issue.resolution_date` dans `Issue.resolution_real_issue_date` pour les plaintes qui ont
une date de résolution mais pas de date réelle de résolution sur le terrain.

Ne remplace jamais une date réelle déjà saisie.

Usage :
    python manage.py copy_resolution_date_to_real            # applique
    python manage.py copy_resolution_date_to_real --dry-run  # affiche seulement le nombre
"""
from django.core.management.base import BaseCommand
from django.db.models import F
from django.utils import timezone

from issue.models import Issue


class Command(BaseCommand):
    help = "Copy resolution_date into resolution_real_issue_date when the latter is empty."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Show the count without writing.')

    def handle(self, *args, dry_run=False, **options):
        queryset = Issue.objects.filter(
            resolution_real_issue_date__isnull=True,
            resolution_date__isnull=False,
        )

        if dry_run:
            self.stdout.write(f'[dry-run] Issues to update: {queryset.count()}')
            return

        # `updated_at` est avancé explicitement (`.update()` n'applique pas auto_now) pour que
        # les mobiles reçoivent la nouvelle valeur au prochain pull.
        updated = queryset.update(
            resolution_real_issue_date=F('resolution_date'),
            updated_at=timezone.now(),
        )
        self.stdout.write(f'Issues updated: {updated}')
