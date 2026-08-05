"""Migre les pièces jointes binaires (documents de la base CouchDB `grm_attachments`, portant
uniquement des `_attachments`) vers Postgres (`issue.Attachment`, fichiers stockés via
`FileField`). Écrit une table de correspondance JSON (bd_id CouchDB -> id Attachment Postgres),
réutilisée par `migrate_grm_issues` pour rattacher chaque `Reason` à son `Attachment`.

À exécuter AVANT `migrate_grm_issues` (voir CLAUDE.md §6). Rejouable : les documents déjà
importés (retrouvés via leur nom de fichier + taille dans le mapping existant) sont ignorés.

Usage : python manage.py migrate_grm_attachments
"""
import json
import mimetypes
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand

from client import get_db
from issue.models import Attachment

MAPPING_PATH = Path(settings.BASE_DIR).parent / 'scripts' / 'grm_attachments_mapping.json'


class Command(BaseCommand):
    help = 'Migre les pièces jointes binaires depuis CouchDB (grm_attachments) vers Postgres.'

    def handle(self, *args, **options):
        db = get_db(settings.COUCHDB_GRM_ATTACHMENT_DATABASE)

        mapping = {}
        if MAPPING_PATH.exists():
            mapping = json.loads(MAPPING_PATH.read_text(encoding='utf-8'))

        count = 0
        for doc in db:
            doc_id = doc['_id']
            if doc_id in mapping:
                continue  # déjà migré lors d'un run précédent

            attachments_meta = doc.get('_attachments') or {}
            for filename, meta in attachments_meta.items():
                binary = doc.get_attachment(filename, attachment_type='binary')
                content_type = meta.get('content_type') or mimetypes.guess_type(filename)[0] or 'application/octet-stream'

                attachment = Attachment.objects.create(
                    issue=None,  # rattaché après-coup par migrate_grm_issues via reason.attachment
                    legacy_bd_id=doc_id,
                    file_name=filename,
                    content_type=content_type,
                    size=meta.get('length', 0),
                )
                attachment.file.save(filename, ContentFile(binary), save=True)
                mapping[doc_id] = str(attachment.id)
                count += 1

        MAPPING_PATH.parent.mkdir(parents=True, exist_ok=True)
        MAPPING_PATH.write_text(json.dumps(mapping), encoding='utf-8')

        self.stdout.write(self.style.SUCCESS(
            f'attachments: {count} nouvelle(s) pièce(s) jointe(s) migrée(s), '
            f'{len(mapping)} au total dans {MAPPING_PATH}'
        ))
