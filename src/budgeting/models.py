from django.db import models

from grm.models_base import TimestampedSyncModel, safe_json_value
from issue.models import Adl

# ---------------------------------------------------------------------------
# Domaine "budget participatif" — jusqu'ici uniquement porté par les champs
# `phases`/`bp_projects` du document CouchDB `adl` (base `eadls`), sans aucune
# représentation relationnelle (aucun modèle Django, aucune migration nulle part dans ce
# backend — confirmé par exploration : dashboard/participatory_budget/ n'est qu'un tableau de
# bord en lecture seule contre des vues CouchDB, `dashboard/subprojects/` est un stub
# "under_construction"). Modèles construits ici en miroir du JSON existant, avec le même
# patron que le domaine `issue` (TimestampedSyncModel : UUID, is_deleted, created_at/updated_at).
# ---------------------------------------------------------------------------


class Phase(TimestampedSyncModel):
    adl = models.ForeignKey(Adl, on_delete=models.CASCADE, related_name='phases')
    ordinal = models.IntegerField()
    title = models.CharField(max_length=255)
    open_at = models.DateTimeField(null=True, blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f'{self.title} ({self.adl})'


class Task(TimestampedSyncModel):
    # Types observés côté frontend (PhaseTasks/containers/Content.js route sur `task.type`) :
    # 'multiple_list_activity' -> RegisterSubprojects, 'vote_activity' -> RegisterVotesActivity,
    # 'input_activity' -> BudgetAllocation (le montant `bp_amount` n'est renseigné que pour ce
    # type), tout le reste -> DocumentTask (type générique par défaut).
    TYPE_MULTIPLE_LIST_ACTIVITY = 'multiple_list_activity'
    TYPE_VOTE_ACTIVITY = 'vote_activity'
    TYPE_INPUT_ACTIVITY = 'input_activity'
    TYPE_DOCUMENT = 'document'
    TASK_TYPES = [
        (TYPE_MULTIPLE_LIST_ACTIVITY, 'Multiple list activity'),
        (TYPE_VOTE_ACTIVITY, 'Vote activity'),
        (TYPE_INPUT_ACTIVITY, 'Input activity'),
        (TYPE_DOCUMENT, 'Document'),
    ]

    STATUS_NOT_STARTED = 'not-started'
    STATUS_IN_PROGRESS = 'in-progress'
    STATUS_COMPLETED = 'completed'
    STATUS_CHOICES = [
        (STATUS_NOT_STARTED, 'Not started'),
        (STATUS_IN_PROGRESS, 'In progress'),
        (STATUS_COMPLETED, 'Completed'),
    ]

    phase = models.ForeignKey(Phase, on_delete=models.CASCADE, related_name='tasks')
    ordinal = models.IntegerField(default=0)
    task_type = models.CharField(max_length=30, choices=TASK_TYPES, default=TYPE_DOCUMENT)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_NOT_STARTED)
    notes = models.TextField(blank=True, null=True)
    open_at = models.DateTimeField(null=True, blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    # Position GPS capturée à la sauvegarde (DocumentTask), cf. expo-location côté client.
    location = models.JSONField(blank=True, null=True)
    # Uniquement renseigné pour task_type == 'input_activity' (élaboration du budget).
    bp_amount = models.DecimalField(max_digits=14, decimal_places=2, blank=True, null=True)

    @property
    def location_value(self):
        return safe_json_value(self.location)

    def __str__(self):
        return f'{self.title} ({self.phase})'


class BpProject(TimestampedSyncModel):
    """Sous-projet soumis au budget participatif (ex `bp_projects[]` du document `adl`)."""
    adl = models.ForeignKey(Adl, on_delete=models.CASCADE, related_name='bp_projects')
    # Identifiant lisible généré côté client (`${commune}-${n}`), conservé tel quel pour
    # compatibilité d'affichage — la clé primaire réelle reste l'UUID (TimestampedSyncModel).
    external_code = models.CharField(max_length=100, blank=True, null=True)
    district_name = models.CharField(max_length=255, blank=True, null=True)
    subproject_name = models.CharField(max_length=255, blank=True, null=True)
    subproject_description = models.TextField(blank=True, null=True)

    # Décompte des votes par tranche d'âge / genre (jeune 15-40, adulte 40-65, senior 65+ ;
    # m = homme, f = femme), saisis via RegisterVotesActivity.
    vote_ym = models.IntegerField(default=0)
    vote_yf = models.IntegerField(default=0)
    vote_mm = models.IntegerField(default=0)
    vote_mf = models.IntegerField(default=0)
    vote_om = models.IntegerField(default=0)
    vote_of = models.IntegerField(default=0)

    def __str__(self):
        return self.subproject_name or self.external_code or str(self.id)


class BudgetAllocationEntry(TimestampedSyncModel):
    """Journal d'allocation budgétaire, append-only (ex `bp_projects[].budget_allocated[]`)."""
    bp_project = models.ForeignKey(BpProject, on_delete=models.CASCADE, related_name='budget_allocations')
    description = models.CharField(max_length=255, blank=True, null=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    entry_date = models.DateTimeField()

    def __str__(self):
        return f'{self.amount} - {self.bp_project}'
