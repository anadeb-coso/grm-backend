"""Remplit `Issue.resolution_date` des plaintes résolues qui ne l'ont pas, à partir de leur
historique de statut : date de la PREMIÈRE ligne `IssueStatusStory` au statut final (« Résolue »).

L'application mobile n'écrivait pas cette date avant la correction de 2026-11 (seul le web le
faisait), et les documents CouchDB migrés l'avaient vide. Les plaintes résolues sans ligne
d'historique de résolution restent sans date (aucune source fiable).

`resolution_real_issue_date` (date réelle sur le terrain) n'est volontairement PAS rattrapée :
elle n'a jamais été saisie, on ne peut pas la deviner.

Usage :
    python manage.py backfill_resolution_date            # applique
    python manage.py backfill_resolution_date --dry-run  # affiche seulement les comptes
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Min, Q
from django.utils import timezone

from issue.models import Issue


class Command(BaseCommand):
    help = "Fill missing Issue.resolution_date from the first 'resolved' status story."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Show counts without writing.')

    def handle(self, *args, dry_run=False, **options):
        candidates = (
            Issue.objects
            .filter(is_deleted=False, status__final_status=True, resolution_date__isnull=True)
            .annotate(first_resolution=Min(
                'issue_status_stories__datetime',
                filter=Q(issue_status_stories__status__final_status=True,
                         issue_status_stories__is_deleted=False),
            ))
        )
        total = candidates.count()
        to_fill = [(i.pk, i.first_resolution) for i in candidates if i.first_resolution]

        if not dry_run:
            with transaction.atomic():
                now = timezone.now()
                for pk, dt in to_fill:
                    # `updated_at` est avancé explicitement (`.update()` n'applique pas auto_now)
                    # pour que les mobiles reçoivent la date au prochain pull.
                    Issue.objects.filter(pk=pk).update(resolution_date=dt, updated_at=now)

        self.stdout.write(
            f"{'[dry-run] ' if dry_run else ''}Resolved issues without resolution_date: {total} | "
            f"filled from status history: {len(to_fill)} | left empty (no history): {total - len(to_fill)}"
        )
