import uuid
import requests
from io import BytesIO
from django.core.files.base import ContentFile
from django.http import FileResponse, Http404, HttpResponseRedirect
from django.db.models import Q
from drf_yasg.openapi import IN_QUERY, Parameter
from drf_yasg.utils import swagger_auto_schema
from rest_framework import generics, parsers
from rest_framework.response import Response

from attachments.serializers import (
    AttachmentUpdateStatusSerializer, IssueFileSerializer,
    TaskFileSerializer
)
from budgeting.models import Phase, Task
from issue.models import Adl, Attachment, Issue


def _filter_by_pk_if_uuid(queryset, value):
    """`doc_id` peut être soit un ancien `_id` CouchDB (déjà tenté via `legacy_couch_id`), soit
    directement l'UUID Postgres — mais un `doc_id` arbitraire côté client (chaîne quelconque)
    ferait planter `.filter(pk=...)` avec une `ValidationError` non gérée plutôt qu'un 404 propre
    si elle n'est pas un UUID valide."""
    try:
        uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return queryset.none()
    return queryset.filter(pk=value)


class GetAttachmentAPIView(generics.GenericAPIView):
    """Résout une pièce jointe historique à partir de son ancien `_id` CouchDB (base
    `grm_attachments`), conservé sur `Attachment.legacy_bd_id` (cf. migrate_grm_attachments.py),
    et redirige vers son URL réelle (S3/media Django). Le paramètre `db` de l'ancienne API
    (choix entre la base d'attachments `grm`/participatory budget) n'a plus d'utilité : les deux
    types de pièces jointes vivent désormais dans la même table Postgres `Attachment`."""

    @swagger_auto_schema(
        manual_parameters=[
            Parameter(
                'db',
                IN_QUERY,
                description='Conservé pour compatibilité ascendante avec les anciens clients, sans effet.',
                type='string'
            ),
            Parameter(
                'download',
                IN_QUERY,
                description='Si présent, force un vrai téléchargement (Content-Disposition: attachment) '
                             "plutôt que l'affichage inline par défaut du navigateur/S3.",
                type='string'
            )
        ]
    )
    def get(self, request, *args, **kwargs):
        attachment = Attachment.objects.filter(Q(id=kwargs['id']) | Q(legacy_bd_id=kwargs['id'])).first()
        if not attachment or not attachment.file:
            raise Http404
        
        url = attachment.file.url.split('?')[0] if '?' in attachment.file.url else attachment.file.url
        
        if request.GET.get('download'):
            r = requests.get(url, stream=True)
            r.raise_for_status()

            filename = attachment.file_name or kwargs['name']
            response = FileResponse(
                BytesIO(r.content),
                content_type=attachment.content_type or "application/octet-stream",
            )
            
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            
            return response

        
        return HttpResponseRedirect(url)


class UploadTaskAttachmentAPIView(generics.GenericAPIView):
    """Upload d'une pièce jointe de tâche du budget participatif, par un client pré-WatermelonDB
    encore en usage. `doc_id`/`phase`/`task` reprennent la sémantique historique (`doc_id` = ancien
    `_id` CouchDB de l'`adl`, `phase`/`task` = position 1-based dans les tableaux imbriqués du
    document) — résolus ici contre `Adl.legacy_couch_id` puis `Phase.ordinal`/`Task.ordinal`.
    Le `attachment_id` client (identifiant d'un slot dans le tableau CouchDB `tasks[].attachments`)
    n'a pas d'équivalent Postgres : simplification documentée, on crée directement une nouvelle
    `Attachment` liée à la tâche plutôt que de rejouer la logique de correspondance par slot."""
    serializer_class = TaskFileSerializer
    parser_classes = (parsers.FormParser, parsers.MultiPartParser)

    @swagger_auto_schema(
        responses={201: AttachmentUpdateStatusSerializer()},
        operation_description="Allowed file size less than or equal to 2 MB"
    )
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        adl = Adl.objects.filter(legacy_couch_id=data['doc_id']).first() \
            or _filter_by_pk_if_uuid(Adl.objects, data['doc_id']).first()
        if not adl:
            raise Http404

        phase = Phase.objects.filter(adl=adl, ordinal=data['phase']).first()
        task = Task.objects.filter(phase=phase, ordinal=data['task']).first() if phase else None
        if not task:
            raise Http404

        file = data['file']
        # cf. sync/attachment_views.py::AttachmentUploadView pour la raison du `ContentFile` :
        # évite un `RuntimeError: Input ... is not supported` boto3/s3transfer avec le fichier
        # `InMemoryUploadedFile`/`TemporaryUploadedFile` brut de `request.FILES`.
        attachment = Attachment.objects.create(
            task=task, file=ContentFile(file.read(), name=file.name), file_name=file.name,
            content_type=file.content_type or '', size=file.size,
        )
        return Response({'ok': True, 'id': str(attachment.id), 'rev': None}, status=201)


class UploadIssueAttachmentAPIView(generics.GenericAPIView):
    """Upload d'une pièce jointe d'issue par un client pré-WatermelonDB encore en usage. `doc_id`
    reprend la sémantique historique (ancien `_id` CouchDB de l'issue), résolu ici contre
    `Issue.legacy_couch_id`. Le `attachment_id` client (identifiant d'un slot dans les tableaux
    imbriqués CouchDB `attachments`/`reasons`/`resolution_files`/`escalation_reasons`) n'a pas
    d'équivalent Postgres : simplification documentée (même principe que pour les tâches du budget
    participatif, cf. UploadTaskAttachmentAPIView) — on crée directement une nouvelle `Attachment`
    liée à l'issue plutôt que de rejouer la correspondance par slot dans 4 tableaux différents."""
    serializer_class = IssueFileSerializer
    parser_classes = (parsers.FormParser, parsers.MultiPartParser)

    @swagger_auto_schema(
        responses={201: AttachmentUpdateStatusSerializer()},
        operation_description="Allowed file size less than or equal to 2 MB"
    )
    def post(self, request, *args, **kwargs):
        data = request.data
        file = data.get('file')
        if not file:
            raise Http404

        issue = None
        doc_id = data.get('doc_id')
        if doc_id:
            issue = Issue.objects.filter(legacy_couch_id=doc_id).first() \
                or _filter_by_pk_if_uuid(Issue.objects, doc_id).first()
            if not issue:
                raise Http404

        # cf. sync/attachment_views.py::AttachmentUploadView pour la raison du `ContentFile`.
        attachment = Attachment.objects.create(
            issue=issue, file=ContentFile(file.read(), name=file.name), file_name=file.name,
            content_type=file.content_type or '', size=file.size,
        )
        return Response({
            'message': 'OK',
            'fileUrl': attachment.url,
            'bd_id': str(attachment.id),
        }, status=201)
