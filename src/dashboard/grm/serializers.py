"""Pont entre les vues/templates historiques du dashboard `grm` (écrites contre des documents
CouchDB mutables : `doc['x'] = y` puis `doc.save()`) et les modèles Postgres `issue.models`.

`issue_to_legacy_dict(issue)` reproduit la forme exacte des anciens documents CouchDB à partir
d'une instance `Issue` Postgres (mêmes clés imbriquées : `category: {id, name, ...}`,
`reasons: [...]`, etc.) — même principe que `grm-frontend/src/utils/issueLegacyShape.js` côté
mobile, pour éviter de réécrire les ~2000 lignes de templates/vues qui lisent déjà `doc.category.
name`, `doc.reasons`, etc.

`LegacyIssueDoc` enveloppe ce dict : les lectures (`doc['x']`, `doc.get('x')`, `'x' in doc`)
continuent de fonctionner sans changement ; les écritures scalaires (`doc['x'] = y` puis
`doc.save()`) sont traduites vers les champs Postgres réels de `Issue`. Les ajouts de
commentaires/raisons/pièces jointes/historique de statut, qui dans l'ancien code consistaient à
faire `liste.insert(0, x)` puis réassigner `doc['comments'] = liste`, doivent désormais passer
par les méthodes explicites (`add_comment`, `add_reason`, `add_escalation_reason`,
`add_status_story`, `add_attachment`) qui créent immédiatement l'enregistrement Postgres
correspondant — un diff générique de liste ne suffit pas dès qu'une pièce jointe réelle
(FileField) est impliquée.
"""
from django.utils import timezone

from issue.models import (
    Attachment, Comment, EscalationLevel, EscalationReason, Issue, IssueAgeGroup, IssueCategory,
    IssueStatus, IssueType, Reason, IssueStatusStory,
)

# Les documents CouchDB stockaient les dates en chaînes ISO-8601 (`%Y-%m-%dT%H:%M:%S.%fZ`) — de
# nombreux templates/tags historiques (dashboard/templatetags/custom_tags.py::string_to_date,
# get_date, get_hour, date_order_format, get_days_until_today/date) et du JS front continuent de
# `.split('T')`/`datetime.strptime(...)` sur cette forme. `issue_to_legacy_dict` reproduit donc
# fidèlement des chaînes plutôt que des objets `datetime` Python, pour ne pas avoir à réécrire ces
# templates.
_LEGACY_DATETIME_FORMAT = '%Y-%m-%dT%H:%M:%S.%fZ'


def _dt_str(value):
    if value is None:
        return None
    return timezone.localtime(value, timezone.utc).strftime(_LEGACY_DATETIME_FORMAT) if timezone.is_aware(value) else value.strftime(_LEGACY_DATETIME_FORMAT)


# Rang hiérarchique fixe (Canton -> Préfecture/Région (même palier) -> Pays, cf.
# grm-frontend/src/screens/Home/IssueActions/containers/Content.js::get_next_administrative_level)
# utilisé pour déterminer le niveau d'escalade COURANT, plutôt que `created_at` : sur les issues
# migrées depuis CouchDB, `escalation_administrativelevels[]` était stocké du plus récent au plus
# ancien (comme tous les autres tableaux legacy), et `migrate_grm_issues.py` a recréé les lignes
# `EscalationLevel` dans cet ordre littéral plutôt que chronologique réel — le tout premier niveau
# atteint (ex. Canton) se retrouve donc avec le `created_at` le plus récent, et inversement.
_ESCALATION_LEVEL_RANK = {'Village': 1, 'Canton': 2, 'Commune': 3, 'Prefecture': 4, 'Region': 5, 'Country': 6}


def _current_escalation_level(issue):
    levels = list(issue.escalation_levels.filter(is_deleted=False))
    if not levels:
        return None
    return max(levels, key=lambda lvl: (_ESCALATION_LEVEL_RANK.get(lvl.administrative_level, 0), lvl.created_at))


def _attachment_to_legacy(attachment):
    if attachment is None:
        return None
    return {
        'id': str(attachment.pk),
        'pk': str(attachment.pk),
        'name': attachment.file_name,
        'url': attachment.url,
        'local_url': '',
        'uploaded': True,
        'bd_id': str(attachment.pk),
    }


def _reason_to_legacy(reason):
    data = {
        'id': str(reason.pk),
        'pk': str(reason.pk),
        'subject': reason.subject,
        'comment': reason.comment,
        'user_id': reason.user_id,
        'user_name': reason.user_name,
        'name': reason.user_name,
        'due_at': reason.due_at,
        'type': 'comment' if reason.subject == 'comment' else 'file',
    }
    if reason.attachment_id:
        data.update(_attachment_to_legacy(reason.attachment))
    return data


def issue_to_legacy_dict(issue):
    """`issue` doit être préchargée avec `select_related('status', 'category', 'age_group',
    'issue_type')` et `prefetch_related('comments', 'reasons', 'escalation_reasons',
    'escalation_levels', 'issue_status_stories', 'attachments')` (voir `IssueMixin.dispatch`)."""
    status = issue.status
    category = issue.category
    age_group = issue.age_group
    issue_type = issue.issue_type

    # `.filter(is_deleted=False)` partout ci-dessous : ces tables sont synchronisées avec le
    # mobile (tombstone logique, cf. grm.models_base.TimestampedSyncModel) — un enregistrement
    # supprimé (depuis le mobile via push, ou depuis ce même dashboard) reste en base jusqu'à sa
    # purge différée (issue.tasks.cleanup_old_tombstones) et continuait donc, sans ce filtre, à
    # s'afficher indéfiniment ici malgré sa suppression.
    reasons_qs = list(issue.reasons.filter(is_deleted=False).order_by('-created_at'))
    reasons = [_reason_to_legacy(r) for r in reasons_qs]
    resolution_files = [d for d in reasons if d.get('subject') == 'resolution']
    linked_attachment_ids = {r.attachment_id for r in reasons_qs if r.attachment_id}

    comments = [
        {
            'id': c.author_id,
            'pk': str(c.pk),
            'name': c.author_name,
            'comment': c.comment,
            'due_at': _dt_str(c.due_at),
        }
        for c in issue.comments.filter(is_deleted=False).order_by('-created_at')
    ]

    escalation_reasons = [
        {
            'id': er.user_id,
            'pk': str(er.pk),
            'user_id': er.user_id,
            'user_name': er.user_name,
            'name': er.user_name,
            'comment': er.comment,
            'due_at': _dt_str(er.due_at),
            **({'attachment': _attachment_to_legacy(er.attachment)} if er.attachment_id else {}),
        }
        for er in issue.escalation_reasons.filter(is_deleted=False).order_by('-created_at')
    ]

    issue_status_stories = [
        {
            'pk': str(s.pk),
            'status': {'id': s.status.legacy_id, 'name': s.status.name} if s.status_id else None,
            'user': {
                'id': s.user_id,
                'username': s.user.username if s.user_id else None,
                'full_name': s.user_full_name,
            },
            'comment': s.comment,
            'datetime': _dt_str(s.datetime),
        }
        for s in issue.issue_status_stories.filter(is_deleted=False).order_by('-created_at')
    ]

    latest_escalation_level = _current_escalation_level(issue)
    escalation_administrativelevels = []
    if latest_escalation_level:
        escalation_administrativelevels = [{
            'escalate_to': {
                'administrative_id': (
                    str(latest_escalation_level.administrative_id)
                    if latest_escalation_level.administrative_id else None
                ),
                'name': latest_escalation_level.name,
                'administrative_level': latest_escalation_level.administrative_level,
            },
            'comment': None,
            'due_at': _dt_str(latest_escalation_level.due_at),
        }]

    attachments = [
        _attachment_to_legacy(a)
        for a in issue.attachments.filter(is_deleted=False).order_by('-created_at')
        if a.pk not in linked_attachment_ids
    ]

    last_unresolved_reason = issue.last_unresolved_reason()
    if last_unresolved_reason:
        unresolved_reason = {
            'id': last_unresolved_reason.pk,
            'pk': str(last_unresolved_reason.pk),
            'comment': last_unresolved_reason.comment,
            'user_id': last_unresolved_reason.user_id,
            'user_name': last_unresolved_reason.user_full_name,
            'name': last_unresolved_reason.user_full_name,
            'due_at': _dt_str(last_unresolved_reason.datetime),
        }
    else:
        unresolved_reason = None

    last_escalation_reason = issue.last_escalation_reason()
    if last_escalation_reason:
        escalate_reason = {
            'id': last_escalation_reason.pk,
            'pk': str(last_escalation_reason.pk),
            'comment': last_escalation_reason.comment,
            'user_id': last_escalation_reason.user_id,
            'user_name': last_escalation_reason.user_name,
            'name': last_escalation_reason.user_name,
            'due_at': _dt_str(last_escalation_reason.due_at),
        }
    else:
        escalate_reason = None

    return {
        '_id': str(issue.pk),
        'id': issue.pk,
        'type': 'issue',
        'auto_increment_id': issue.auto_increment_id,
        'internal_code': issue.internal_code,
        'tracking_code': issue.tracking_code,
        'description': issue.description,
        'original_description': issue.original_description,
        'confirmed': issue.confirmed,
        'citizen': issue.citizen,
        'contact_medium': issue.contact_medium,
        'citizen_type': issue.citizen_type,
        'citizen_group_1': {'id': None, 'name': issue.citizen_group_1} if issue.citizen_group_1 else '',
        'citizen_group_2': {'id': None, 'name': issue.citizen_group_2} if issue.citizen_group_2 else '',
        'citizen_or_group': issue.citizen_or_group,
        'citizen_age_group': {'id': age_group.legacy_id, 'name': age_group.name} if age_group else '',
        'source': issue.source,
        'publish': issue.publish,
        'publish_date': _dt_str(issue.publish_date),
        'notification_send': issue.notification_send,
        'ongoing_issue': issue.ongoing_issue,
        'event_recurrence': issue.event_recurrence,
        'resolution_days': issue.resolution_days,
        'created_date': _dt_str(issue.created_date),
        'intake_date': _dt_str(issue.intake_date),
        'issue_date': _dt_str(issue.issue_date),
        'resolution_date': _dt_str(issue.resolution_date),
        'reject_date': _dt_str(issue.reject_date),
        'research_result': issue.research_result,
        'escalate_flag': issue.escalate_flag,
        'status': ({
            'id': status.legacy_id,
            'name': status.name,
            'final_status': status.final_status,
            'initial_status': status.initial_status,
            'rejected_status': status.rejected_status,
            'open_status': status.open_status,
            'unresolved_status': status.unresolved_status,
            'eligible_status': status.eligible_status,
            'not_eligible_status': status.not_eligible_status,
        } if status else None),
        'category': ({
            'id': category.legacy_id,
            'name': category.name,
            'label': category.label,
            'abbreviation': category.abbreviation,
            'confidentiality_level': category.confidentiality_level,
            'redirection_protocol': category.redirection_protocol,
            'assigned_department': category.assigned_department_value,
            'administrative_level': category.administrative_level,
        } if category else None),
        'issue_type': {'id': issue_type.legacy_id, 'name': issue_type.name} if issue_type else None,
        'assignee': {'id': issue.assignee_id, 'name': issue.assignee_name} if issue.assignee_id else '',
        'reporter': {'id': issue.reporter_id, 'name': issue.reporter_name} if issue.reporter_id else None,
        'administrative_region': {
            'administrative_id': (
                str(issue.administrative_region_id) if issue.administrative_region_id else None
            ),
            'name': issue.administrative_region_name,
        },
        'location_info': issue.location_info_value,
        'structure_in_charge': issue.structure_in_charge_value,
        'contact_information': issue.contact_information_value,
        'commune': issue.commune_value,
        'comments': comments,
        'reasons': reasons,
        'resolution_files': resolution_files,
        'escalation_reasons': escalation_reasons,
        'escalation_administrativelevels': escalation_administrativelevels,
        'issue_status_stories': issue_status_stories,
        'attachments': attachments,
        'unresolved_reason': unresolved_reason,
        'escalate_reason': escalate_reason,
    }


def _resolve_legacy_fk(model, value):
    if value in (None, ''):
        return None
    legacy_id = value.get('id') if isinstance(value, dict) else value
    if legacy_id in (None, ''):
        return None
    return model.objects.filter(legacy_id=legacy_id).first()


# Clés du dict "vue legacy" qui se traduisent directement (même nom) vers un champ scalaire
# `Issue` sans transformation.
_DIRECT_SCALAR_FIELDS = {
    'internal_code', 'tracking_code', 'auto_increment_id', 'description', 'original_description',
    'confirmed', 'citizen', 'contact_medium', 'citizen_type', 'citizen_or_group', 'source',
    'publish', 'publish_date', 'notification_send', 'ongoing_issue', 'event_recurrence',
    'resolution_days', 'created_date', 'intake_date', 'issue_date', 'resolution_date',
    'reject_date', 'research_result', 'escalate_flag', 'location_info', 'structure_in_charge',
    'contact_information', 'commune',
}

# Clés gérées via les méthodes explicites `add_*` de `LegacyIssueDoc` (persistées immédiatement,
# pas via le diff scalaire de `.save()`), ou purement dérivées/en lecture seule.
_IGNORED_ON_SAVE = {
    'comments', 'reasons', 'resolution_files', 'escalation_reasons',
    'escalation_administrativelevels', 'issue_status_stories', 'attachments',
    '_id', 'id', 'type',
    # Champs CouchDB historiques sans colonne Postgres dédiée : le texte est de toute façon
    # conservé de façon permanente dans le Comment/Reason correspondant (cf. add_comment/
    # add_reason) ; on perd seulement le pré-remplissage du formulaire si l'utilisateur rouvre la
    # modale sans avoir soumis — simplification documentée (CLAUDE.md, migration dashboard web).
    'open_reason', 'unresolved_reason', 'escalate_reason', 'reject_reason', '_comment',
    'open_date', 'unresolved_date', 'escalate_date', 'unpublish_date', 'gender', 'created_by',
}


def translate_scalar_field(key, value):
    """Traduit une clé/valeur du dict legacy vers `{champ_postgres: valeur}` pour `Issue.objects.
    filter(pk=...).update(...)`. Retourne `{}` si la clé n'a pas d'équivalent (silencieusement
    ignorée, cf. `_IGNORED_ON_SAVE`) ou si elle correspond à un préfixe dynamique connu
    (`description_<timestamp>`, historique d'anciennes descriptions avant publication répétée —
    non repris en Postgres, cf. simplification ci-dessus)."""
    if key in _DIRECT_SCALAR_FIELDS:
        return {key: value}
    if key in _IGNORED_ON_SAVE or key.startswith('description_'):
        return {}
    if key == 'status':
        obj = _resolve_legacy_fk(IssueStatus, value)
        return {'status_id': obj.pk} if obj else {}
    if key == 'category':
        obj = _resolve_legacy_fk(IssueCategory, value)
        return {'category_id': obj.pk} if obj else {}
    if key == 'issue_type':
        obj = _resolve_legacy_fk(IssueType, value)
        return {'issue_type_id': obj.pk} if obj else {}
    if key == 'citizen_age_group':
        if value in (None, ''):
            return {'age_group': None}
        obj = _resolve_legacy_fk(IssueAgeGroup, value)
        return {'age_group_id': obj.pk} if obj else {}
    if key == 'citizen_group_1':
        return {'citizen_group_1': value.get('name') if isinstance(value, dict) else value}
    if key == 'citizen_group_2':
        return {'citizen_group_2': value.get('name') if isinstance(value, dict) else value}
    if key == 'assignee':
        if value in (None, ''):
            return {'assignee_id': None, 'assignee_name': None}
        return {'assignee_id': value.get('id'), 'assignee_name': value.get('name')}
    if key == 'reporter':
        if value in (None, ''):
            return {'reporter_id': None, 'reporter_name': None}
        return {'reporter_id': value.get('id'), 'reporter_name': value.get('name')}
    if key == 'administrative_region':
        if value in (None, ''):
            return {'administrative_region_id': None, 'administrative_region_name': None}
        administrative_id = value.get('administrative_id')
        return {
            'administrative_region_id': int(administrative_id) if administrative_id not in (None, '') else None,
            'administrative_region_name': value.get('name'),
        }
    return {}


class LegacyIssueDoc(dict):
    """Émule un `cloudant.document.Document` (dict mutable + `.save()`) au-dessus d'une `Issue`
    Postgres. `doc['x'] = y` puis `doc.save()` continue de fonctionner pour tous les champs
    scalaires connus (cf. `translate_scalar_field`) ; pour les listes (commentaires, raisons,
    pièces jointes, historique de statut), utiliser les méthodes `add_*` ci-dessous, qui
    persistent immédiatement l'enregistrement Postgres correspondant."""

    def __init__(self, issue):
        self.issue = issue
        super().__init__(issue_to_legacy_dict(issue))
        self._dirty = {}

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self._dirty[key] = value

    def save(self):
        update_fields = {}
        for key, value in self._dirty.items():
            update_fields.update(translate_scalar_field(key, value))
        if update_fields:
            # `updated_at` (auto_now=True) n'est automatiquement rafraîchi que par `Model.save()`,
            # jamais par `QuerySet.update()` (comportement documenté de Django) — sans le forcer
            # explicitement ici, toute modification faite depuis le dashboard web (description,
            # statut, catégorie, assignation...) restait invisible pour le pull incrémental mobile
            # (`sync/views.py::PullView` ne détecte que `updated_at > last_pulled_at`) : l'issue
            # semblait à jour côté serveur mais ne remontait plus jamais côté mobile, même après un
            # rafraîchissement manuel.
            update_fields['updated_at'] = timezone.now()
            Issue.objects.filter(pk=self.issue.pk).update(**update_fields)
            for field_name, field_value in update_fields.items():
                setattr(self.issue, field_name, field_value)
        self._dirty = {}

    def refresh(self):
        """Recharge le dict legacy depuis les enregistrements Postgres actuels (après un `add_*`
        ou une modification externe) — utile quand un view method relit `self.doc['comments']`
        juste après l'avoir modifié."""
        self.clear()
        self.update(issue_to_legacy_dict(self.issue))

    # --- Ajouts persistés immédiatement (remplacent liste.insert(0, x) + doc.save()) ----------

    def add_comment(self, comment, user=None, due_at=None):
        Comment.objects.create(
            issue=self.issue,
            author_id=user.id if user else None,
            author_name=user.name if user else None,
            comment=comment,
            due_at=due_at or timezone.now(),
        )
        self.refresh()

    def add_reason(self, subject='reason', comment=None, user=None, due_at=None, attachment=None):
        record = Reason.objects.create(
            issue=self.issue,
            subject=subject,
            comment=comment,
            user_id=user.id if user else None,
            user_name=user.name if user else None,
            due_at=due_at or timezone.now(),
            attachment=attachment,
        )
        self.refresh()
        return record

    def add_escalation_reason(self, comment, user=None, due_at=None, attachment=None):
        record = EscalationReason.objects.create(
            issue=self.issue,
            comment=comment,
            user_id=user.id if user else None,
            user_name=user.name if user else None,
            due_at=due_at or timezone.now(),
            attachment=attachment,
        )
        self.refresh()
        return record

    def add_escalation_level(self, administrative_level, administrative_id=None, name=None, due_at=None):
        record = EscalationLevel.objects.create(
            issue=self.issue,
            administrative_level=administrative_level,
            administrative_id=administrative_id,
            name=name,
            due_at=due_at or timezone.now(),
        )
        self.refresh()
        return record

    def add_status_story(self, status_legacy_dict, comment, user=None):
        status = _resolve_legacy_fk(IssueStatus, status_legacy_dict)
        IssueStatusStory.objects.create(
            issue=self.issue,
            status=status,
            user=user,
            user_full_name=user.name if user else None,
            comment=comment,
            datetime=timezone.now(),
        )
        self.refresh()

    def add_attachment(self, file, subject=None, user=None):
        """Crée l'`Attachment` réel (upload Django `FileField`) — remplace l'ancien
        `client.upload_file(file, COUCHDB_GRM_ATTACHMENT_DATABASE)`. Si `subject` est fourni, crée
        aussi le `Reason` qui la référence (équivalent de l'ancien `reasons.insert(0, attachment)`)
        ; sinon la pièce jointe est rattachée directement à l'issue (`attachments[]`)."""
        attachment = Attachment.objects.create(
            issue=self.issue,
            file=file,
            file_name=file.name,
            content_type=getattr(file, 'content_type', '') or 'application/octet-stream',
            size=file.size,
        )
        if subject:
            self.add_reason(subject=subject, user=user, due_at=timezone.now(), attachment=attachment)
        else:
            self.refresh()
        return attachment
