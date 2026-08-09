from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from budgeting.models import BpProject, BudgetAllocationEntry, Phase, Task
from issue.models import (
    Adl, Attachment, Comment, EscalationLevel, EscalationReason, Issue, IssueAgeGroup,
    IssueCategory, IssueCitizenGroup1, IssueCitizenGroup2, IssueDepartment, IssueStatus,
    IssueStatusStory, IssueType, Reason,
)
from sync.models import SyncLog
from sync.serializers import (
    AdlSerializer, AttachmentPullSerializer, BpProjectSyncSerializer,
    BudgetAllocationEntrySyncSerializer, CommentSyncSerializer, EscalationLevelSyncSerializer,
    EscalationReasonSyncSerializer, IssueAgeGroupSerializer, IssueCategorySerializer,
    IssueCitizenGroup1Serializer, IssueCitizenGroup2Serializer, IssueDepartmentSerializer,
    IssueStatusStorySyncSerializer, IssueStatusSerializer, IssueSyncSerializer,
    IssueTypeSerializer, PhaseSyncSerializer, ReasonSyncSerializer, TaskSyncSerializer,
)

from dashboard.tasks import (
    check_issues, send_sms_message, escalate_issues, send_a_new_issue_notification,
    send_issue_status_notifications,
)


# Tables synchronisées en écriture (pull + push) depuis le mobile, visibles par tous les
# utilisateurs autorisés (pas de filtrage par propriétaire).
SYNC_WRITABLE_MODELS = {
    'issues': (Issue, IssueSyncSerializer),
    'comments': (Comment, CommentSyncSerializer),
    'issue_status_stories': (IssueStatusStory, IssueStatusStorySyncSerializer),
    'reasons': (Reason, ReasonSyncSerializer),
    'escalation_reasons': (EscalationReason, EscalationReasonSyncSerializer),
    'escalation_levels': (EscalationLevel, EscalationLevelSyncSerializer),
}

# Référentiels : poussés en pull seul, jamais de push venant du mobile (CLAUDE.md §2).
#
# `attachments` est également en lecture seule ici : sa création reste exclusivement gérée par
# `AttachmentUploadView` (flux HTTP multipart séparé, CLAUDE.md §3.7) — l'inclure en écriture
# dans ce protocole JSON créerait un doublon serveur (id local ≠ id serveur avant la correction
# apportée à `AttachmentUploadView.post`). Sans cette entrée, aucun appareil autre que celui ayant
# fait l'upload n'apprenait jamais l'existence d'une pièce jointe (preuve de résolution, décision/
# investigation avec photo/PDF) : `enqueuePendingDownloads()` ne regarde que les lignes déjà
# présentes localement, et ces lignes n'étaient jamais créées faute de diffusion par le pull.
SYNC_READONLY_MODELS = {
    'issue_statuses': (IssueStatus, IssueStatusSerializer),
    'issue_categories': (IssueCategory, IssueCategorySerializer),
    'issue_age_groups': (IssueAgeGroup, IssueAgeGroupSerializer),
    'issue_types': (IssueType, IssueTypeSerializer),
    'issue_departments': (IssueDepartment, IssueDepartmentSerializer),
    'issue_citizen_groups_1': (IssueCitizenGroup1, IssueCitizenGroup1Serializer),
    'issue_citizen_groups_2': (IssueCitizenGroup2, IssueCitizenGroup2Serializer),
    'adls': (Adl, AdlSerializer),
    'attachments': (Attachment, AttachmentPullSerializer),
}

# Domaine "budget participatif" (budgeting/models.py) : personnel à un facilitateur — jamais
# partagé entre utilisateurs, contrairement aux tables ci-dessus. `owner_lookup` est le chemin
# ORM (depuis le modèle) jusqu'au champ `auth.User` du facilitateur propriétaire, utilisé pour
# filtrer le pull au `request.user` courant.
SYNC_OWNED_MODELS = {
    'phases': (Phase, PhaseSyncSerializer, 'adl__representative'),
    'tasks': (Task, TaskSyncSerializer, 'phase__adl__representative'),
    'bp_projects': (BpProject, BpProjectSyncSerializer, 'adl__representative'),
    'budget_allocations': (BudgetAllocationEntry, BudgetAllocationEntrySyncSerializer, 'bp_project__adl__representative'),
}

SYNC_WRITABLE_MODELS = {
    **SYNC_WRITABLE_MODELS,
    **{name: (Model, Serializer) for name, (Model, Serializer, _owner) in SYNC_OWNED_MODELS.items()},
}

ALL_SYNCED_MODELS = {**SYNC_WRITABLE_MODELS, **SYNC_READONLY_MODELS}
OWNER_LOOKUPS = {name: owner for name, (_m, _s, owner) in SYNC_OWNED_MODELS.items()}

PAGE_SIZE = 500


def _user_administrative_ids(user):
    """Union des 4 champs `Adl.*administrative*_ids` sur TOUS les `Adl` non supprimés rattachés à
    `user` (jamais un seul via `.first()`) : `authentication.models.create_or_update_user`
    (signal `post_save` sur `User`) crée automatiquement un `Adl` vide dès l'inscription d'un
    compte — un représentant peut donc avoir plusieurs lignes `Adl` (celle auto-créée, plus
    celle(s) réellement renseignée(s) via le dashboard/la migration `migrate_eadls`). Sans union,
    piocher `.first()` retournerait un résultat non déterministe (`Adl` a pour pk un UUID, et
    `.first()` trie implicitement par pk faute d'`ordering` explicite)."""
    administrative_ids = set()
    for adl in Adl.objects.filter(representative=user, is_deleted=False):
        for values in (
            adl.administrative_region_ids_value, adl.smallest_administrative_level_ids_value,
            adl.additional_administrative_region_ids_value,
            adl.additional_smallest_administrative_level_ids_value,
        ):
            administrative_ids.update(str(v) for v in (values or []))
    return administrative_ids


def _issue_full_access(user):
    """True si `user` peut voir/synchroniser TOUTES les issues, indépendamment de ses localités
    d'intervention : `GovernmentWorker.administrative_id == "1"` (même convention de portée
    nationale que `sync.administrative_levels_views.AdministrativeLevelsView`), ou "1" inclus
    dans les `Adl.administrative_region_ids` d'un des facilitateurs associés à ce compte."""
    government_worker = getattr(user, 'governmentworker', None)
    if government_worker and government_worker.administrative_id == "1":
        return True
    return "1" in _user_administrative_ids(user)


def _issue_visibility_filter(user):
    """`Q()` restreignant les `Issue` visibles par `user` au pull à : ses localités
    d'intervention (les 4 champs `Adl.*administrative*_ids`, cf. `issue.models.Adl`), les issues
    qu'il a enregistrées (`reporter`), et celles qui lui sont assignées (`assignee`). Retourne
    `None` si `user` a un accès complet (`_issue_full_access`) — dans ce cas l'appelant ne doit
    appliquer aucun filtre."""
    if _issue_full_access(user):
        return None

    administrative_ids = _user_administrative_ids(user)
    region_ids = [int(v) for v in administrative_ids if str(v).lstrip('-').isdigit()]
    return Q(administrative_region_id__in=region_ids) | Q(reporter=user) | Q(assignee=user)


def _issue_owned_by(user, existing_instance, record):
    """Restreint les écritures mobile (push) sur `Issue` aux seules issues que `user` a
    enregistrées ou qui lui sont assignées : c'est uniquement sur celles-ci qu'il aura besoin de
    faire des modifications depuis le mobile, quelle que soit l'étendue de sa visibilité en
    lecture (`_issue_visibility_filter` peut, elle, inclure des issues d'autres agents situées
    dans ses localités d'intervention)."""
    if existing_instance is not None:
        return existing_instance.reporter_id == user.id or existing_instance.assignee_id == user.id
    reporter_id = record.get('reporter')
    assignee_id = record.get('assignee')
    return (
        (reporter_id is not None and str(reporter_id) == str(user.id))
        or (assignee_id is not None and str(assignee_id) == str(user.id))
    )


def _update_pull_sync_log(request, last_pulled_at_dt):
    device_id = request.GET.get('device_id')
    if not device_id or not request.user or not request.user.is_authenticated:
        return
    SyncLog.objects.update_or_create(
        device_id=device_id,
        user=request.user,
        defaults={'last_pulled_at': last_pulled_at_dt},
    )


def _update_push_sync_log(request):
    device_id = request.data.get('device_id')
    if not device_id or not request.user or not request.user.is_authenticated:
        return
    now = datetime.now(tz=dt_timezone.utc)
    SyncLog.objects.update_or_create(
        device_id=device_id,
        user=request.user,
        defaults={'last_push_at': now, 'last_pulled_at': now},
    )


class PullView(APIView):
    """Endpoint `pull` du protocole WatermelonDB. Trois comportements notables :

    1. **Pagination** : chaque table est paginée séparément (offset simple, tri stable par
       `updated_at, id`). Tant qu'une table a des lignes au-delà de la page courante,
       `has_more=True` et un `cursor` opaque est renvoyé ; le frontend doit le renvoyer tel quel
       à l'appel suivant sans changer `last_pulled_at`.
    2. **Full resync forcé** : si `last_pulled_at` du client est plus vieux que
       `TOMBSTONE_MAX_AGE_DAYS`, les tombstones de suppression ont pu être purgées
       (issue.tasks.cleanup_old_tombstones) — un diff incrémental ne serait plus fiable. On
       renvoie alors `force_full_resync: true` sans diff : le client doit vider sa base locale
       et retélécharger l'intégralité de l'état serveur (avec barre de progression, cf.
       grm-frontend/src/database/sync.js).
    3. **Tables "possédées"** (`SYNC_OWNED_MODELS`, domaine budget participatif) : filtrées par
       `request.user` via `owner_lookup` — jamais diffusées à d'autres facilitateurs.
    4. **Issues scopées par localité** : la table `issues` est en plus filtrée par
       `_issue_visibility_filter` — un utilisateur ne reçoit que les issues de ses localités
       d'intervention (`Adl.*administrative*_ids`), celles qu'il a enregistrées, et celles qui
       lui sont assignées, sauf s'il a un accès complet (`_issue_full_access`, id "1").
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        last_pulled_at = int(request.GET.get('last_pulled_at') or 0)
        server_now = datetime.now(tz=dt_timezone.utc)

        if last_pulled_at:
            last_pulled_dt = datetime.fromtimestamp(last_pulled_at / 1000, tz=dt_timezone.utc)
            stale_cutoff = server_now - timedelta(days=settings.TOMBSTONE_MAX_AGE_DAYS)
            if last_pulled_dt < stale_cutoff:
                _update_pull_sync_log(request, server_now)
                return Response({
                    'force_full_resync': True,
                    'changes': {},
                    'timestamp': int(server_now.timestamp() * 1000),
                    'has_more': False,
                    'cursor': None,
                })
        else:
            last_pulled_dt = datetime.fromtimestamp(0, tz=dt_timezone.utc)

        raw_cursor = request.GET.get('cursor') or ''
        offsets = self._parse_cursor(raw_cursor)

        # Calculé une seule fois par requête (indépendant de `last_pulled_at`/pagination) :
        # `None` signifie accès complet, sinon un `Q()` appliqué uniquement à la table `issues`
        # ci-dessous (cf. docstring de la classe, point 4).
        issue_visibility_q = _issue_visibility_filter(request.user)

        changes = {}
        next_offsets = {}
        has_more = False

        for table_name, (Model, Serializer) in ALL_SYNCED_MODELS.items():
            offset = offsets.get(table_name, 0)
            owner_lookup = OWNER_LOOKUPS.get(table_name)
            owner_filter = {owner_lookup: request.user} if owner_lookup else {}
            is_issues_table = table_name == 'issues'

            # Le client WatermelonDB est configuré avec `sendCreatedAsUpdated: true`
            # (grm-frontend/src/database/sync.js) : par convention documentée de la librairie
            # (sync/impl/applyRemote.js), quand ce flag est actif le serveur doit renvoyer TOUS
            # les enregistrements non supprimés (nouveaux ou modifiés) dans `updated`, jamais
            # dans `created` — sinon WatermelonDB logue à chaque pull un diagnostic non bloquant
            # mais permanent (`[Sync] 'sendCreatedAsUpdated' option is enabled, and yet server
            # sends some records as 'created'`). On ne distingue donc plus create vs update ici.
            changed_qs = Model.objects.filter(
                Q(created_at__gt=last_pulled_dt) | Q(updated_at__gt=last_pulled_dt),
                is_deleted=False, **owner_filter,
            )
            if is_issues_table and issue_visibility_q is not None:
                changed_qs = changed_qs.filter(issue_visibility_q)
            changed_qs = changed_qs.order_by('updated_at', 'id')

            all_changed_ids = list(changed_qs.values_list('id', flat=True))
            page_ids = all_changed_ids[offset:offset + PAGE_SIZE]
            table_has_more = len(all_changed_ids) > offset + PAGE_SIZE

            table_changes = {
                'created': [],
                'updated': Serializer(Model.objects.filter(id__in=page_ids), many=True).data,
            }
            # `is_readonly` ne restreint que ce que `PushView` accepte EN ÉCRITURE depuis le
            # mobile (cf. commentaire de classe) — ça ne veut pas dire que ces tables ne sont
            # jamais supprimées côté serveur : `attachments` en particulier est couramment
            # supprimée depuis le dashboard web (dashboard/grm/views.py::IssueAttachmentDeleteView)
            # et `adls` peut être désactivée (authentication/utils.py::delete_adl_user_adl). Avant
            # ce correctif, cette branche renvoyait toujours `[]` pour TOUTES les tables en lecture
            # seule : ces suppressions restaient invisibles pour le mobile, indéfiniment, même après
            # un rafraîchissement manuel. On calcule donc le tombstone de la même façon pour toutes
            # les tables synchronisées, écriture ou lecture seule.
            deleted_qs = Model.objects.filter(
                updated_at__gt=last_pulled_dt, is_deleted=True, **owner_filter,
            )
            if is_issues_table and issue_visibility_q is not None:
                deleted_qs = deleted_qs.filter(issue_visibility_q)
            deleted_qs = deleted_qs.order_by('updated_at', 'id')
            table_changes['deleted'] = list(deleted_qs.values_list('id', flat=True)) if offset == 0 else []

            changes[table_name] = table_changes

            if table_has_more:
                has_more = True
                next_offsets[table_name] = offset + PAGE_SIZE

        if not has_more:
            _update_pull_sync_log(request, server_now)

        
        try:
            check_issues()
            escalate_issues()
            send_sms_message()
            send_a_new_issue_notification()
            send_issue_status_notifications()
        except Exception as exc:
            pass
        
        return Response({
            'force_full_resync': False,
            'changes': changes,
            'timestamp': int(server_now.timestamp() * 1000),
            'has_more': has_more,
            'cursor': self._encode_cursor(next_offsets) if has_more else None,
        })

    @staticmethod
    def _parse_cursor(raw):
        result = {}
        for part in raw.split(','):
            if ':' in part:
                table, offset = part.split(':')
                result[table] = int(offset)
        return result

    @staticmethod
    def _encode_cursor(offsets):
        return ','.join(f'{table}:{offset}' for table, offset in offsets.items())


class PushView(APIView):
    """Endpoint `push`. Seules les tables de `SYNC_WRITABLE_MODELS` acceptent des écritures —
    les référentiels (`SYNC_READONLY_MODELS`) sont ignorés s'ils apparaissent dans `changes` (le
    client ne doit normalement jamais les modifier).

    Validation des FK : les `ModelSerializer` génèrent des `PrimaryKeyRelatedField` pour chaque
    FK (y compris la FK cross-db `Issue.administrative_region`, résolue via
    `grm.routers.MisRouter` vers la base `mis`) — `is_valid(raise_exception=True)` échoue donc
    proprement avec un 400 explicite si une référence (statut, catégorie, niveau administratif...)
    n'existe pas, plutôt que de laisser remonter une `IntegrityError` en base. Le `try/except`
    autour de la transaction est un filet de sécurité pour les cas restants.

    Restriction spécifique à `issues` : contrairement au pull (qui peut renvoyer des issues
    d'autres agents situées dans les localités d'intervention de l'utilisateur, cf.
    `_issue_visibility_filter`), le push d'une `Issue` n'est accepté que si l'utilisateur en est
    l'auteur (`reporter`) ou l'assigné (`assignee`) — c'est uniquement sur celles-ci qu'il a
    besoin de faire des modifications depuis le mobile (`_issue_owned_by`), y compris pour un
    utilisateur ayant un accès complet en lecture."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        changes = request.data.get('changes', {})

        try:
            with transaction.atomic():
                for table_name, (Model, Serializer) in SYNC_WRITABLE_MODELS.items():
                    table_changes = changes.get(table_name, {})
                    is_issues_table = table_name == 'issues'

                    for record in table_changes.get('created', []):
                        if is_issues_table and not _issue_owned_by(request.user, None, record):
                            raise PermissionDenied(
                                'You can only sync issues you registered or that are assigned to you.',
                            )
                        serializer = Serializer(data=record)
                        serializer.is_valid(raise_exception=True)
                        Model.objects.update_or_create(
                            id=record['id'], defaults=serializer.validated_data,
                        )

                    for record in table_changes.get('updated', []):
                        if is_issues_table:
                            existing = Model.objects.filter(id=record['id']).first()
                            if existing is not None and not _issue_owned_by(request.user, existing, record):
                                raise PermissionDenied(
                                    'You can only sync issues you registered or that are assigned to you.',
                                )
                        self._merge_update(Model, Serializer, record)

                    for record_id in table_changes.get('deleted', []):
                        if is_issues_table:
                            existing = Model.objects.filter(id=record_id).first()
                            if existing is not None and not _issue_owned_by(request.user, existing, {}):
                                raise PermissionDenied(
                                    'You can only sync issues you registered or that are assigned to you.',
                                )
                        # `updated_at` doit être forcé explicitement : `QuerySet.update()` ne
                        # déclenche jamais `auto_now` (contrairement à `Model.save()`). Sans ça, le
                        # tombstone (`is_deleted=True`) posé par CET appareil ne serait jamais vu
                        # par les AUTRES appareils au pull (`PullView` filtre les suppressions sur
                        # `updated_at > last_pulled_at`) : la suppression resterait silencieusement
                        # locale au lieu de se propager.
                        Model.objects.filter(id=record_id).update(
                            is_deleted=True, updated_at=datetime.now(tz=dt_timezone.utc),
                        )
        except ValidationError as exc:
            # `serializer.is_valid(raise_exception=True)` lève cette exception DRF (distincte de
            # `django.core.exceptions.ValidationError` ci-dessous) — non rattrapée explicitement
            # jusqu'ici, elle remontait au gestionnaire d'exception par défaut de DRF avec une
            # forme de réponse différente des deux autres branches. `transaction.atomic()` a de
            # toute façon déjà annulé tout le lot à ce stade (comportement inchangé) ; on
            # uniformise seulement la forme de la réponse pour le client mobile.
            return Response({'detail': 'Validation error', 'errors': exc.detail}, status=400)
        except DjangoValidationError as exc:
            return Response(
                {'detail': 'Validation error', 'errors': exc.message_dict if hasattr(exc, 'message_dict') else str(exc)},
                status=400,
            )
        except IntegrityError as exc:
            return Response(
                {'detail': 'Integrity error: a referenced record does not exist', 'errors': str(exc)},
                status=400,
            )

        _update_push_sync_log(request)


        try:
            check_issues()
            escalate_issues()
            send_sms_message()
            send_a_new_issue_notification()
            send_issue_status_notifications()
        except Exception as exc:
            pass

        return Response(status=204)

    @staticmethod
    def _merge_update(Model, Serializer, record):
        """Merge champ à champ : n'écrase que les colonnes listées dans `_changed` (métadonnée
        WatermelonDB), pour ne pas piétiner une modification concurrente côté serveur sur
        d'autres colonnes."""
        changed_fields = [f for f in record.get('_changed', '').split(',') if f]

        instance = Model.objects.filter(id=record['id']).first()
        if instance is None:
            serializer = Serializer(data=record)
            serializer.is_valid(raise_exception=True)
            Model.objects.create(**serializer.validated_data)
            return

        if not changed_fields:
            serializer = Serializer(instance, data=record)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return

        partial_payload = {k: v for k, v in record.items() if k in changed_fields}
        serializer = Serializer(instance, data=partial_payload, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()


class InactiveDevicesView(APIView):
    """Tableau de bord (JSON, réservé au staff) des appareils inactifs depuis plus de
    `SYNC_INACTIVE_DEVICE_DAYS` jours (CLAUDE.md §9 : item non coché "Faire remonter dans un
    dashboard/log les appareils inactifs depuis plus de 30 jours")."""
    permission_classes = [IsAdminUser]

    def get(self, request):
        cutoff = datetime.now(tz=dt_timezone.utc) - timedelta(days=settings.SYNC_INACTIVE_DEVICE_DAYS)
        inactive = SyncLog.objects.filter(last_pulled_at__lt=cutoff).order_by('last_pulled_at')
        return Response([
            {
                'device_id': log.device_id,
                'user': log.user.email if log.user else None,
                'last_pulled_at': log.last_pulled_at,
                'last_push_at': log.last_push_at,
                'days_inactive': (datetime.now(tz=dt_timezone.utc) - log.last_pulled_at).days,
            }
            for log in inactive
        ])


class TokenBlacklistView(APIView):
    """`djangorestframework-simplejwt==4.8.0` (contrainte Django 3.2) n'expose pas encore
    `rest_framework_simplejwt.views.TokenBlacklistView` — réimplémentée ici à partir de
    `RefreshToken.blacklist()` (fourni par l'app `token_blacklist`, déjà installée)."""
    permission_classes = [AllowAny]

    def post(self, request):
        refresh = request.data.get('refresh')
        if not refresh:
            raise ValidationError({'refresh': 'This field is required.'})
        try:
            RefreshToken(refresh).blacklist()
        except TokenError as exc:
            raise ValidationError({'refresh': str(exc)})
        return Response(status=200)
