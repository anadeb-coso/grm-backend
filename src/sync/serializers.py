from rest_framework import serializers

from administrativelevels.models import AdministrativeLevel
from budgeting.models import BpProject, BudgetAllocationEntry, Phase, Task
from issue.models import (
    Adl, Attachment, Comment, EscalationLevel, EscalationReason, Issue, IssueAgeGroup,
    IssueCategory, IssueCitizenGroup1, IssueCitizenGroup2, IssueDepartment, IssueStatus,
    IssueStatusStory, IssueType, Reason,
)

# ---------------------------------------------------------------------------
# Modèles synchronisés en écriture (pull + push) depuis le mobile.
# ---------------------------------------------------------------------------


class IssueSyncSerializer(serializers.ModelSerializer):
    # `status`/`category`/`issue_type`/`administrative_region` sont `null=True` au niveau modèle
    # (le dashboard web crée un brouillon d'issue rempli progressivement sur plusieurs étapes,
    # cf. dashboard/grm/views.py::StartNewIssueView) mais restent obligatoires pour le protocole
    # de sync mobile, qui pousse toujours une issue déjà complète en un seul push (CLAUDE.md §9 :
    # "valider finement les FK au push").
    status = serializers.PrimaryKeyRelatedField(queryset=IssueStatus.objects.all(), required=True)
    category = serializers.PrimaryKeyRelatedField(queryset=IssueCategory.objects.all(), required=True)
    issue_type = serializers.PrimaryKeyRelatedField(queryset=IssueType.objects.all(), required=True)
    # Cross-db (base `mis`, routée automatiquement par grm.routers.MisRouter) : le queryset n'a
    # pas besoin de `.using('mis')` explicite, le routeur s'en charge pour tout modèle de l'app
    # `administrativelevels`.
    administrative_region = serializers.PrimaryKeyRelatedField(queryset=AdministrativeLevel.objects.all(), required=True)

    class Meta:
        model = Issue
        # `original_description` (donnée anonymisée/chiffrée, cf. issue/models.py) n'est
        # volontairement jamais exposée au protocole de sync mobile.
        exclude = ['original_description']


class CommentSyncSerializer(serializers.ModelSerializer):
    class Meta:
        model = Comment
        fields = '__all__'


class IssueStatusStorySyncSerializer(serializers.ModelSerializer):
    class Meta:
        model = IssueStatusStory
        fields = '__all__'


class ReasonSyncSerializer(serializers.ModelSerializer):
    class Meta:
        model = Reason
        fields = '__all__'


class AttachmentSyncSerializer(serializers.ModelSerializer):
    url = serializers.ReadOnlyField()

    class Meta:
        model = Attachment
        fields = [
            'id', 'issue', 'task', 'url', 'file_name', 'content_type', 'size',
            'is_deleted', 'created_at', 'updated_at',
        ]


class AttachmentPullSerializer(serializers.ModelSerializer):
    """Utilisé uniquement par `PullView` (`sync/views.py`, table `attachments` en lecture seule) —
    distinct de `AttachmentSyncSerializer` (réponse de `AttachmentUploadView`) car le nom de
    colonne WatermelonDB attendu est `remote_url`, pas `url` (grm-frontend/src/database/schema.js).
    `upload_status` est forcé à `'done'` : tout enregistrement provenant du serveur est par
    définition déjà uploadé — sans ça, `SnackBarCheckFileUnsyncComponent` afficherait à tort une
    alerte "fichiers non synchronisés" pour des pièces jointes créées par d'autres utilisateurs.
    `local_uri`/`download_status` sont volontairement absents (champs purement locaux au mobile,
    cf. issue/models.py::Attachment qui ne les a pas) : WatermelonDB ne touche alors pas à ces
    colonnes pour un enregistrement déjà connu localement."""
    remote_url = serializers.ReadOnlyField(source='url')
    upload_status = serializers.SerializerMethodField()

    class Meta:
        model = Attachment
        fields = [
            'id', 'issue', 'task', 'remote_url', 'file_name', 'content_type', 'size',
            'upload_status', 'is_deleted', 'created_at', 'updated_at',
        ]

    def get_upload_status(self, obj):
        return 'done'


class EscalationReasonSyncSerializer(serializers.ModelSerializer):
    class Meta:
        model = EscalationReason
        fields = '__all__'


class EscalationLevelSyncSerializer(serializers.ModelSerializer):
    class Meta:
        model = EscalationLevel
        fields = '__all__'


# ---------------------------------------------------------------------------
# Domaine "budget participatif" (CLAUDE.md n'en parle pas explicitement, mais suit le même
# patron que le domaine `issue` — voir budgeting/models.py). Toujours personnel à un facilitateur
# (`Adl.representative`) : contrairement aux référentiels `issue_*`, ces tables sont filtrées par
# utilisateur au pull (voir sync/views.py::SYNC_OWNED_MODELS), jamais diffusées à tous les mobiles.
# ---------------------------------------------------------------------------


class PhaseSyncSerializer(serializers.ModelSerializer):
    class Meta:
        model = Phase
        fields = '__all__'


class TaskSyncSerializer(serializers.ModelSerializer):
    class Meta:
        model = Task
        fields = '__all__'


class BpProjectSyncSerializer(serializers.ModelSerializer):
    class Meta:
        model = BpProject
        fields = '__all__'


class BudgetAllocationEntrySyncSerializer(serializers.ModelSerializer):
    class Meta:
        model = BudgetAllocationEntry
        fields = '__all__'


# ---------------------------------------------------------------------------
# Référentiels : lecture seule côté mobile (jamais de push), cf. CLAUDE.md §2.
# ---------------------------------------------------------------------------


class IssueStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = IssueStatus
        fields = '__all__'


class IssueCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = IssueCategory
        fields = '__all__'


class IssueAgeGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = IssueAgeGroup
        fields = '__all__'


class IssueTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = IssueType
        fields = '__all__'


class IssueDepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = IssueDepartment
        fields = '__all__'


class AdlSerializer(serializers.ModelSerializer):
    class Meta:
        model = Adl
        fields = '__all__'


class IssueCitizenGroup1Serializer(serializers.ModelSerializer):
    class Meta:
        model = IssueCitizenGroup1
        fields = '__all__'


class IssueCitizenGroup2Serializer(serializers.ModelSerializer):
    class Meta:
        model = IssueCitizenGroup2
        fields = '__all__'
