from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _
from datetime import datetime

from grm.models_base import BaseModel, TimestampedSyncModel, safe_json_value

# Create your models here.

class Wave(BaseModel):
    number = models.IntegerField()
    description = models.TextField()
    administrative_ids = models.JSONField(verbose_name=_('administrative levels')) # list of administrative levels ids
    begin = models.DateField()
    end = models.DateField(blank=True, null=True)

    @property
    def administrative_ids_value(self):
        return safe_json_value(self.administrative_ids)


# ---------------------------------------------------------------------------
# Modèles Postgres synchronisés avec le mobile (WatermelonDB), migrés depuis les
# documents CouchDB des bases `grm`/`eadls`. `legacy_id`/
# `legacy_couch_id` conservent l'identifiant CouchDB d'origine pour permettre des
# scripts de migration idempotents (`update_or_create`), rejouables sans doublon.
# ---------------------------------------------------------------------------

class IssueStatus(TimestampedSyncModel):
    legacy_id = models.IntegerField(unique=True, null=True, blank=True)
    name = models.CharField(max_length=100)
    final_status = models.BooleanField(default=False)
    initial_status = models.BooleanField(default=False)
    rejected_status = models.BooleanField(default=False)
    open_status = models.BooleanField(default=False)
    unresolved_status = models.BooleanField(default=False)
    eligible_status = models.BooleanField(default=False)
    not_eligible_status = models.BooleanField(default=False)

    def __str__(self):
        return self.name


class IssueDepartment(TimestampedSyncModel):
    legacy_id = models.IntegerField(unique=True, null=True, blank=True)
    name = models.CharField(max_length=255)
    head_name = models.CharField(max_length=255, blank=True, null=True)
    head = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='headed_issue_departments',
    )

    def __str__(self):
        return self.name


class IssueCategory(TimestampedSyncModel):
    legacy_id = models.IntegerField(unique=True, null=True, blank=True)
    name = models.CharField(max_length=255)
    label = models.CharField(max_length=255, blank=True, null=True)
    abbreviation = models.CharField(max_length=20, blank=True, null=True)
    confidentiality_level = models.CharField(max_length=50, blank=True, null=True)
    redirection_protocol = models.IntegerField(null=True, blank=True)
    # Ces champs pointent vers des structures imbriquées côté CouchDB
    # ({"name": ..., "id": ..., "administrative_level": ..., "assigment_protocol": ...}) :
    # conservés en JSON, pas normalisés en table à part (jamais interrogés indépendamment).
    assigned_department = models.JSONField(blank=True, null=True)
    assigned_appeal_department = models.JSONField(blank=True, null=True)
    assigned_escalation_department = models.JSONField(blank=True, null=True)
    administrative_level = models.CharField(max_length=50, blank=True, null=True)

    @property
    def assigned_department_value(self):
        return safe_json_value(self.assigned_department)

    @property
    def assigned_appeal_department_value(self):
        return safe_json_value(self.assigned_appeal_department)

    @property
    def assigned_escalation_department_value(self):
        return safe_json_value(self.assigned_escalation_department)

    def __str__(self):
        return self.name


class IssueAgeGroup(TimestampedSyncModel):
    legacy_id = models.IntegerField(unique=True, null=True, blank=True)
    name = models.CharField(max_length=50)

    def __str__(self):
        return self.name


class IssueCitizenGroup1(TimestampedSyncModel):
    """Référentiel `issue_citizen_group_1` (CouchDB) — absent du plan initial CLAUDE.md,
    découvert lors de la bascule de CitizenReportContactInfo.js. Même patron que IssueAgeGroup."""
    legacy_id = models.IntegerField(unique=True, null=True, blank=True)
    name = models.CharField(max_length=50)

    def __str__(self):
        return self.name


class IssueCitizenGroup2(TimestampedSyncModel):
    """Référentiel `issue_citizen_group_2` (CouchDB), voir IssueCitizenGroup1."""
    legacy_id = models.IntegerField(unique=True, null=True, blank=True)
    name = models.CharField(max_length=50)

    def __str__(self):
        return self.name


class IssueType(TimestampedSyncModel):
    legacy_id = models.IntegerField(unique=True, null=True, blank=True)
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name


class Adl(TimestampedSyncModel):
    """Facilitateur/représentant (ex document `adl` de la base CouchDB `eadls`)."""
    legacy_couch_id = models.CharField(max_length=64, unique=True, null=True, blank=True)
    name = models.CharField(max_length=255)
    location_name = models.CharField(max_length=255, blank=True, null=True)
    representative_name = models.CharField(max_length=255, blank=True, null=True)
    representative = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='adl_representations',
    )
    department = models.CharField(max_length=100, blank=True, null=True)
    # Périmètre de villages/cantons gérés par ce facilitateur : IDs numériques référençant
    # administrativelevels.AdministrativeLevel (base `mis`), jamais dupliqués ici (CLAUDE.md §2.1).
    administrative_region_ids = models.JSONField(default=list, blank=True)
    smallest_administrative_level_ids = models.JSONField(default=list, blank=True)
    additional_administrative_region_ids = models.JSONField(default=list, blank=True)
    additional_smallest_administrative_level_ids = models.JSONField(default=list, blank=True)
    # Champ découvert lors de la migration du dashboard web
    # (authentication/models.py::get_assignee, dernier recours d'assignation) — absent du plan
    # initial CLAUDE.md. Pas de champ `photo` dédié : c'est `representative.photo`
    # (authentication.models.User, déjà existant) qui fait foi, la photo du document CouchDB
    # `adl` n'étant qu'une copie dénormalisée de celle-ci (cf. dashboard/adls/views.py).
    village_secretary = models.BooleanField(default=False)

    @property
    def administrative_region_ids_value(self):
        return safe_json_value(self.administrative_region_ids)

    @property
    def smallest_administrative_level_ids_value(self):
        return safe_json_value(self.smallest_administrative_level_ids)

    @property
    def additional_administrative_region_ids_value(self):
        return safe_json_value(self.additional_administrative_region_ids)

    @property
    def additional_smallest_administrative_level_ids_value(self):
        return safe_json_value(self.additional_smallest_administrative_level_ids)

    def __str__(self):
        return self.name


class Issue(TimestampedSyncModel):
    # Ex `_id` du document CouchDB `issue` (base `grm`) — absent du plan initial CLAUDE.md, la clé
    # primaire Postgres étant un nouvel UUID généré à la migration (cf. migrate_grm_issues.py).
    # Nécessaire pour que les anciens endpoints REST pré-WatermelonDB encore routés
    # (issue/views_rest.py, attachments/views.py) puissent résoudre une issue à partir du `doc_id`
    # CouchDB envoyé par une installation mobile pas encore mise à jour.
    legacy_couch_id = models.CharField(max_length=64, unique=True, null=True, blank=True)
    internal_code = models.CharField(max_length=100, unique=True)
    tracking_code = models.CharField(max_length=100, blank=True, null=True)
    auto_increment_id = models.IntegerField()
    description = models.TextField()
    confirmed = models.BooleanField(default=False)

    citizen = models.CharField(max_length=255, blank=True, null=True)
    contact_medium = models.CharField(max_length=50, blank=True, null=True)
    citizen_type = models.CharField(max_length=50, blank=True, null=True)
    citizen_group_1 = models.CharField(max_length=255, blank=True, null=True)
    citizen_group_2 = models.CharField(max_length=255, blank=True, null=True)
    citizen_or_group = models.CharField(max_length=50, blank=True, null=True)

    source = models.CharField(max_length=20, default='mobile')
    publish = models.BooleanField(default=False)
    publish_date = models.DateTimeField(blank=True, null=True)
    notification_send = models.BooleanField(default=False)
    ongoing_issue = models.BooleanField(default=False)
    event_recurrence = models.BooleanField(default=False)
    resolution_days = models.IntegerField(default=0)

    created_date = models.DateTimeField()
    intake_date = models.DateTimeField()
    issue_date = models.DateTimeField()
    resolution_date = models.DateTimeField(blank=True, null=True)
    reject_date = models.DateTimeField(blank=True, null=True)
    research_result = models.TextField(blank=True, null=True)
    # Description anonymisée/chiffrée observée sur certains documents CouchDB legacy
    # (mécanisme Fernet de authentication.models.anonymize_issue_data) : conservée telle quelle
    # pour ne pas perdre de donnée à la migration, jamais exposée au protocole de sync mobile
    # (cf. sync/serializers.py::IssueSyncSerializer qui l'exclut explicitement).
    original_description = models.TextField(blank=True, null=True)

    # `null=True` sur status/category/issue_type/administrative_region : le dashboard web crée un
    # brouillon d'issue (StartNewIssueView) rempli progressivement sur plusieurs étapes
    # (new_issue_step_1..6, cf. dashboard/grm/views.py) — ces FK ne sont connues qu'à partir de
    # l'étape 3/4. Le flux mobile (sync/serializers.py::IssueSyncSerializer), lui, envoie toujours
    # une issue déjà complète en un seul push : aucun impact côté WatermelonDB.
    status = models.ForeignKey(IssueStatus, null=True, blank=True, on_delete=models.PROTECT, related_name='issues')
    category = models.ForeignKey(IssueCategory, null=True, blank=True, on_delete=models.PROTECT, related_name='issues')
    age_group = models.ForeignKey(IssueAgeGroup, null=True, blank=True, on_delete=models.SET_NULL, related_name='issues')
    issue_type = models.ForeignKey(IssueType, null=True, blank=True, on_delete=models.PROTECT, related_name='issues')

    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='assigned_issues',
    )
    assignee_name = models.CharField(max_length=255, blank=True, null=True)
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='reported_issues',
    )
    reporter_name = models.CharField(max_length=255, blank=True, null=True)

    # Référence cross-DB vers administrativelevels.AdministrativeLevel (MySQL `mis`, voir
    # CLAUDE.md §2.1/§4.2.1). `db_constraint=False` : Postgres ne peut pas poser de contrainte FK
    # vers une table qui vit dans une autre base ; l'intégrité est garantie par le routeur
    # `grm.routers.MisRouter` + la validation explicite au push (voir sync/views.py).
    administrative_region = models.ForeignKey(
        'administrativelevels.AdministrativeLevel',
        null=True,
        blank=True,
        on_delete=models.DO_NOTHING,
        db_constraint=False,
        related_name='issues',
    )
    administrative_region_name = models.CharField(max_length=255, blank=True, null=True)

    # Objets "valeur" non normalisés -> JSON (jamais interrogés indépendamment ni partagés
    # entre issues, cf. CLAUDE.md §2).
    location_info = models.JSONField(blank=True, null=True)
    structure_in_charge = models.JSONField(blank=True, null=True)
    contact_information = models.JSONField(blank=True, null=True)
    commune = models.JSONField(blank=True, null=True)

    # Accesseurs "sûrs" pour les 4 champs ci-dessus : certaines issues créées depuis le mobile ont
    # ces colonnes stockées double-encodées (chaîne JSON au lieu de dict, cf. safe_json_value) —
    # observé sur les issues `source='mobile'`, dû au protocole de sync qui transmet tel quel le
    # texte déjà sérialisé par les colonnes `@json` de WatermelonDB (grm-frontend/src/database/
    # schema.js) sans le re-décoder avant l'envoi au serveur.
    @property
    def location_info_value(self):
        return safe_json_value(self.location_info)

    @property
    def structure_in_charge_value(self):
        return safe_json_value(self.structure_in_charge)

    @property
    def contact_information_value(self):
        return safe_json_value(self.contact_information)

    @property
    def commune_value(self):
        return safe_json_value(self.commune)

    # Anti-doublon des SMS envoyés par dashboard/tasks.py::send_sms_message — découvert lors de la
    # migration du dashboard web (Phase 6), absent du plan initial CLAUDE.md.
    accepted_alert_sent = models.BooleanField(default=False)
    rejected_alert_sent = models.BooleanField(default=False)
    closed_alert_sent = models.BooleanField(default=False)

    # Workflow d'escalade (ex `escalate_flag`/`escalation_reasons`/`escalation_administrativelevels`
    # du document CouchDB) — découvert lors de la bascule de IssueActions/containers/Content.js,
    # absent du plan initial CLAUDE.md. `escalate_flag` gèle les actions accept/reject/not-resolve
    # tant qu'une escalade est en cours ; l'historique détaillé vit dans EscalationReason/
    # EscalationLevel ci-dessous (FK `issue`, cf. leurs related_name).
    escalate_flag = models.BooleanField(default=False)

    def __str__(self):
        return self.internal_code
    
    def last_unresolved_reason(self):
        return self.issue_status_stories.filter(
            status__unresolved_status=True, is_deleted=False,
        ).order_by('-created_at').first()

    def last_escalation_reason(self):
        return self.escalation_reasons.filter(is_deleted=False).order_by('-created_at').first()


class Comment(TimestampedSyncModel):
    issue = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    author_name = models.CharField(max_length=255, blank=True, null=True)
    comment = models.TextField()
    due_at = models.DateTimeField()

    # Commentaire saisi par un utilisateur dans la zone « Commentaires » (web ou mobile), par
    # opposition à ceux générés automatiquement par les actions (acceptée, résolue, escaladée...),
    # déjà notifiées par email : seuls les premiers déclenchent les notifications de commentaire
    # (issue/notifications.py).
    is_user_comment = models.BooleanField(default=False)
    # Case « Envoyer par email » (cochée par défaut dans les formulaires) : sans elle, seules les
    # notifications dans l'application (mobile, cloche web) sont créées.
    send_email = models.BooleanField(default=False)
    # Destinataires ajoutés à la main par l'auteur, en plus des membres notifiés d'office.
    notify_emails = models.JSONField(default=list, blank=True)
    notify_user_ids = models.JSONField(default=list, blank=True)
    # Anti-doublon : renseigné dès que les notifications de ce commentaire ont été traitées.
    notifications_processed_at = models.DateTimeField(null=True, blank=True)

    @property
    def notify_emails_value(self):
        return safe_json_value(self.notify_emails) or []

    @property
    def notify_user_ids_value(self):
        return safe_json_value(self.notify_user_ids) or []


class IssueNotification(TimestampedSyncModel):
    """Notification « nouveau commentaire » adressée à un compte : une ligne par destinataire et
    par commentaire (issue/notifications.py). Synchronisée vers le mobile, filtrée sur le
    destinataire, qui ne peut qu'y renseigner `read_at` (sync/views.py)."""
    KIND_COMMENT = 'comment'

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='issue_notifications',
    )
    issue = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name='notifications')
    comment = models.ForeignKey(
        Comment, null=True, blank=True, on_delete=models.CASCADE, related_name='notifications',
    )
    kind = models.CharField(max_length=20, default=KIND_COMMENT)
    read_at = models.DateTimeField(null=True, blank=True)
    # Copies prises au moment de la notification : affichables même quand l'issue n'est pas dans
    # le périmètre synchronisé du destinataire (compte ajouté à la main par l'auteur).
    issue_code = models.CharField(max_length=100, blank=True, null=True)
    comment_text = models.TextField(blank=True, null=True)
    author_name = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['recipient', 'comment'], name='unique_issue_notification_per_comment'),
        ]
        indexes = [models.Index(fields=['recipient', 'read_at'])]


class IssueReadState(models.Model):
    """Dernière ouverture d'une issue par un compte sur le dashboard web (cloche : issues non
    lues)."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='issue_read_states')
    issue = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name='read_states')
    last_read_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'issue'], name='unique_issue_read_state'),
        ]


class NotificationRecipient(models.Model):
    """Destinataire des notifications email des issues (listes de l'équipe MGP), modifiable dans
    l'admin Django. Remplace les listes autrefois codées en dur dans grm/constants.py ; lu par
    issue/notification_recipients.py::recipient_emails."""
    GROUP_SAFEGUARD_SPECIALISTS = 'safeguard_specialists'
    GROUP_SAFEGUARD_ASSISTANTS = 'safeguard_assistants'
    GROUP_COORDINATORS = 'coordinators'
    GROUP_REGIONAL_COORDINATORS = 'regional_coordinators'
    GROUP_OTHER_SPECIALISTS = 'other_specialists'
    GROUP_ANADEB = 'anadeb'
    GROUP_OTHERS = 'others'
    GROUP_CHOICES = (
        (GROUP_SAFEGUARD_SPECIALISTS, _('Safeguard specialists')),
        (GROUP_SAFEGUARD_ASSISTANTS, _('Safeguard specialist assistants')),
        (GROUP_COORDINATORS, _('Coordinators')),
        (GROUP_REGIONAL_COORDINATORS, _('Regional coordinators')),
        (GROUP_OTHER_SPECIALISTS, _('Other specialists')),
        (GROUP_ANADEB, _('ANADEB')),
        (GROUP_OTHERS, _('Others')),
    )

    email = models.EmailField(verbose_name=_('email address'))
    name = models.CharField(max_length=255, blank=True, verbose_name=_('name'))
    group = models.CharField(max_length=40, choices=GROUP_CHOICES, verbose_name=_('list'))
    role = models.CharField(max_length=100, blank=True, verbose_name=_('role'))
    is_active = models.BooleanField(default=True, verbose_name=_('active'))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('notification recipient')
        verbose_name_plural = _('notification recipients')
        ordering = ('group', 'email')
        constraints = [
            models.UniqueConstraint(fields=['group', 'email'], name='unique_notification_recipient_per_group'),
        ]

    def clean(self):
        # Avant la vérification d'unicité de l'admin : « A@x.org » et « a@x.org » sont la même adresse.
        self.email = (self.email or '').strip().lower()

    def save(self, *args, **kwargs):
        self.email = (self.email or '').strip().lower()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.email} ({self.get_group_display()})'


class NotificationBaseline(models.Model):
    """Point de départ du suivi « non lu » d'un compte, posé à sa première consultation de la
    cloche : seules les issues créées ou modifiées après comptent comme non lues (sinon tout
    l'historique existant apparaîtrait non lu à la mise en service)."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notification_baseline')
    since = models.DateTimeField()


class IssueStatusStory(TimestampedSyncModel):
    issue = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name='issue_status_stories')
    status = models.ForeignKey(IssueStatus, on_delete=models.PROTECT, related_name='issue_status_stories')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    user_full_name = models.CharField(max_length=255, blank=True, null=True)
    comment = models.TextField(blank=True, null=True)
    datetime = models.DateTimeField()

    # Anti-doublon de la notification email envoyée par
    # dashboard/tasks.py::send_issue_status_notifications (ouverture/acceptation, investigation/
    # décision, résolution) — un champ par entrée d'historique (et non par `Issue` comme
    # `accepted_alert_sent`/`closed_alert_sent` pour les SMS) car une même issue peut accumuler
    # plusieurs étapes d'investigation, chacune devant déclencher son propre email.
    email_notified = models.BooleanField(default=False)


class Attachment(TimestampedSyncModel):
    def _upload_path(instance, filename):
        return f'grm_attachments/{instance.issue_id or "unassigned"}/{"_".join(filename.split(".")[:-1])}_{datetime.now().strftime("%Y%m%d%H%M%S")}.{filename.split(".")[-1]}'

    issue = models.ForeignKey(Issue, null=True, blank=True, on_delete=models.CASCADE, related_name='attachments')
    # Référence différée (chaîne) vers budgeting.Task : évite un import circulaire, `budgeting`
    # important déjà `issue.models.Adl`. Réutilise ce modèle plutôt que d'en créer un nouveau pour
    # les pièces jointes de DocumentTask (budget participatif).
    task = models.ForeignKey('budgeting.Task', null=True, blank=True, on_delete=models.CASCADE, related_name='attachments')
    # `_id` du document CouchDB source (base `grm_attachments`) — jusqu'ici seulement conservé dans
    # un fichier JSON éphémère (/tmp/grm_attachments_mapping.json) écrit par
    # migrate_grm_attachments.py, perdu au redémarrage. Persisté ici pour que les anciens endpoints
    # REST (attachments/views.py::GetAttachmentAPIView) puissent résoudre un fichier à partir du
    # `bd_id` CouchDB historique.
    legacy_bd_id = models.CharField(max_length=64, unique=True, null=True, blank=True)
    file = models.FileField(upload_to=_upload_path)
    file_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100)
    size = models.PositiveIntegerField(default=0)

    @property
    def url(self):
        return self.file.url if self.file else None

    def __str__(self):
        return self.file_name


class Reason(TimestampedSyncModel):
    """Couvre à la fois `reasons` et `resolution_files` du document CouchDB (un champ `subject`
    les distingue, ex. "resolution")."""
    issue = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name='reasons')
    subject = models.CharField(max_length=50, default='reason')
    comment = models.TextField(blank=True, null=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    user_name = models.CharField(max_length=255, blank=True, null=True)
    due_at = models.DateTimeField(blank=True, null=True)
    attachment = models.ForeignKey(
        Attachment, null=True, blank=True, on_delete=models.SET_NULL, related_name='reasons',
    )


class EscalationReason(TimestampedSyncModel):
    """Historique des motifs d'escalade (ex `issue.escalation_reasons[]` CouchDB)."""
    issue = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name='escalation_reasons')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    user_name = models.CharField(max_length=255, blank=True, null=True)
    comment = models.TextField(blank=True, null=True)
    due_at = models.DateTimeField()
    attachment = models.ForeignKey(
        Attachment, null=True, blank=True, on_delete=models.SET_NULL, related_name='escalation_reasons',
    )


class EscalationLevel(TimestampedSyncModel):
    """Historique des niveaux administratifs successifs d'escalade (ex
    `issue.escalation_administrativelevels[]` CouchDB) — le plus récent (tri par `created_at`
    décroissant) fait foi côté client pour déterminer le niveau courant."""
    issue = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name='escalation_levels')
    administrative_level = models.CharField(max_length=50, blank=True, null=True)
    # Référence informative vers administrativelevels.AdministrativeLevel (base `mis`) : souvent
    # nulle tant que le niveau exact n'a pas été confirmé manuellement (cf. logique frontend
    # `get_next_administrative_level`). Pas de FK stricte pour cette raison.
    administrative_id = models.IntegerField(null=True, blank=True)
    name = models.CharField(max_length=255, blank=True, null=True)
    due_at = models.DateTimeField()