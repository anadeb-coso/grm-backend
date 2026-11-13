"""Reprend le sexe du plaignant (`gender`) des documents CouchDB `issue` (base `grm`) dans
`Issue.gender`, pour les plaintes déjà migrées dont le champ est vide.

Avant 2026-11, la migration CouchDB → Postgres ne reprenait pas ce champ. La correspondance se
fait par `Issue.legacy_couch_id` (= `_id` du document CouchDB). Un sexe déjà renseigné n'est
jamais remplacé.

Usage :
    python manage.py backfill_gender_from_couchdb            # applique
    python manage.py backfill_gender_from_couchdb --dry-run  # affiche seulement le nombre
"""
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from client import get_db
from issue.models import Issue


class Command(BaseCommand):
    help = "Fill empty Issue.gender from the legacy CouchDB issue documents."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Show the count without writing.')

    def handle(self, *args, dry_run=False, **options):
        db = get_db(settings.COUCHDB_GRM_DATABASE)
        couch_genders = {
            doc['_id']: doc['gender']
            for doc in db
            if doc.get('type') == 'issue' and doc.get('gender')
        }

        to_fill = Issue.objects.filter(
            Q(gender__isnull=True) | Q(gender=''),
            legacy_couch_id__in=list(couch_genders),
        ).values_list('pk', 'legacy_couch_id')

        updated = 0
        now = timezone.now()
        for pk, couch_id in to_fill:
            if not dry_run:
                # `updated_at` avancé pour que les mobiles reçoivent la valeur au prochain pull.
                Issue.objects.filter(pk=pk).update(gender=couch_genders[couch_id], updated_at=now)
            updated += 1

        self.stdout.write(f"{'[dry-run] ' if dry_run else ''}Issues updated with gender: {updated}")
