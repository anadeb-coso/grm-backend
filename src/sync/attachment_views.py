import uuid

from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from budgeting.models import Task
from issue.models import Attachment, Issue
from sync.serializers import AttachmentSyncSerializer


class AttachmentUploadView(APIView):
    """Upload d'un fichier (photo, audio, PDF) rattaché à une `Issue` OU à une `Task` (budget
    participatif, écran DocumentTask) Postgres — flux séparé du protocole `pull`/`push`, qui ne
    transporte que du texte/nombre (cf. CLAUDE.md §3.7). Le fichier est déjà compressé côté
    client (grm-frontend/src/files/compression.js) avant l'envoi, `MAX_ATTACHMENT_SIZE` est un
    filet de sécurité supplémentaire."""
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser]

    def post(self, request):
        file_obj = request.FILES.get('file')
        if not file_obj:
            raise ValidationError({'file': 'This field is required.'})

        if file_obj.size > settings.MAX_ATTACHMENT_SIZE:
            raise ValidationError(
                f"Fichier trop volumineux ({file_obj.size / 1024 / 1024:.1f} Mo), "
                f"limite {settings.MAX_ATTACHMENT_SIZE / 1024 / 1024:.0f} Mo."
            )

        issue_id = request.data.get('issue_id')
        issue = None
        if issue_id:
            issue = Issue.objects.filter(id=issue_id).first()
            if issue is None:
                raise ValidationError({'issue_id': 'No such issue.'})

        task_id = request.data.get('task_id')
        task = None
        if task_id:
            task = Task.objects.filter(id=task_id).first()
            if task is None:
                raise ValidationError({'task_id': 'No such task.'})

        defaults = dict(
            issue=issue,
            task=task,
            # `ContentFile` plutôt que l'`InMemoryUploadedFile`/`TemporaryUploadedFile` brut de
            # `request.FILES` : ce dernier peut, selon la taille/le type de fichier, échouer côté
            # boto3/s3transfer avec `RuntimeError: Input ... is not supported` — `s3transfer`
            # (>=0.10) est plus strict sur les objets fichier qu'il accepte, et le wrapper
            # `FileProxyMixin` de Django (readable()/seekable() délégués via `self.file`) ne passe
            # pas toujours ses vérifications de compatibilité. Un `ContentFile` (BytesIO simple,
            # sans indirection) est reconnu de façon fiable par tous les `UploadInputManager` de
            # s3transfer.
            file=ContentFile(file_obj.read(), name=file_obj.name),
            file_name=file_obj.name,
            content_type=file_obj.content_type or 'application/octet-stream',
            size=file_obj.size,
        )

        # Réutilise l'UUID généré côté mobile (`createWithId`, cf. CLAUDE.md §3.4.1) si fourni :
        # sans ça, l'enregistrement local WatermelonDB et l'enregistrement serveur portent deux
        # id différents, et le pull (`attachments` est aussi désormais exposé en lecture seule,
        # cf. sync/views.py) recréerait un doublon local sur l'appareil ayant fait l'upload.
        client_id = request.data.get('id')
        client_uuid = None
        if client_id:
            try:
                client_uuid = uuid.UUID(str(client_id))
            except (ValueError, TypeError):
                client_uuid = None

        if client_uuid:
            attachment, _ = Attachment.objects.update_or_create(id=client_uuid, defaults=defaults)
        else:
            attachment = Attachment.objects.create(**defaults)

        return Response(AttachmentSyncSerializer(attachment).data, status=201)


class AttachmentDeleteView(APIView):
    """Suppression d'une pièce jointe déjà envoyée au serveur — flux séparé du protocole
    `pull`/`push`, symétrique de `AttachmentUploadView` : `attachments` est exclue de
    `SYNC_WRITABLE_MODELS` (cf. sync/views.py), donc une suppression locale WatermelonDB
    (`record.markAsDeleted()`, ex. IssueActions/CitizenReportStep3 "retirer ce fichier") n'était
    jamais transmise au serveur — poussée dans le lot `push` habituel, elle était silencieusement
    ignorée (le serveur n'itère que sur les tables inscriptibles), et WatermelonDB, voyant le push
    réussir quand même, ne la retentait jamais. `files/uploadQueue.js::deletePendingRemovals`
    appelle cet endpoint explicitement avant de marquer la suppression comme traitée localement.

    Tombstone logique (`is_deleted=True` + `updated_at`), pas de suppression physique : cette
    table est aussi exposée en lecture seule au pull (cf. sync/views.py), les AUTRES appareils
    ayant déjà téléchargé ce fichier doivent pouvoir apprendre sa suppression."""
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        updated = Attachment.objects.filter(pk=pk, is_deleted=False).update(
            is_deleted=True, updated_at=timezone.now(),
        )
        if not updated:
            return Response(status=404)
        return Response(status=204)
