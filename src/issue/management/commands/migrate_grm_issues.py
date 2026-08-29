"""Migre les documents `issue` (base CouchDB `grm`) + leurs enfants (comments,
issue_status_stories, reasons/resolution_files) vers Postgres. Prérequis : avoir exécuté
`migrate_grm_reference_data` et `migrate_grm_attachments` avant (voir CLAUDE.md §6).

Rejouable : `update_or_create` sur `internal_code` (clé stable et unique côté CouchDB).
Les issues dont le niveau administratif est introuvable dans `mis` sont ignorées (loguées),
plutôt que de faire échouer toute la migration.

Usage : python manage.py migrate_grm_issues
"""
import json
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_datetime

from administrativelevels.models import AdministrativeLevel
from client import get_db
from issue.models import (
    Attachment, Comment, EscalationLevel, EscalationReason, Issue, IssueAgeGroup, IssueCategory,
    IssueStatus, IssueStatusStory, IssueType, Reason,
)

User = get_user_model()

MAPPING_PATH = Path(settings.BASE_DIR).parent / 'scripts' / 'grm_attachments_mapping.json'


def _dt(value):
    """Convertit une date ISO CouchDB (parfois '' quand non renseignée) en datetime aware."""
    if not value:
        return None
    return parse_datetime(value)


def _user(user_id):
    if not user_id:
        return None
    try:
        return User.objects.filter(pk=int(user_id)).first()
    except (TypeError, ValueError):
        return None


class Command(BaseCommand):
    help = 'Migre les issues (+ comments/issue_status_stories/reasons) depuis CouchDB (grm) vers Postgres.'

    def handle(self, *args, **options):
        db = get_db(settings.COUCHDB_GRM_DATABASE)
        attachments_mapping = {}
        if MAPPING_PATH.exists():
            attachments_mapping = json.loads(MAPPING_PATH.read_text(encoding='utf-8'))

        migrated, skipped = 0, 0

        for doc in db:
            if doc.get('type') != 'issue':
                continue
            doc_id = doc.get('_id')

            try:
                issue = self._migrate_issue(doc, attachments_mapping)
                if issue is None:
                    skipped += 1
                    continue
                self._migrate_comments(doc, issue)
                self._migrate_status_stories(doc, issue)
                self._migrate_reasons(doc, issue, attachments_mapping)
                self._migrate_escalation(doc, issue, attachments_mapping)
                migrated += 1
            except Exception as exc:  # une issue malformée ne doit pas bloquer les autres
                self.stderr.write(self.style.WARNING(f'Issue {doc_id} ignorée ({exc})'))
                skipped += 1

        self.stdout.write(self.style.SUCCESS(f'issues: {migrated} migrée(s), {skipped} ignorée(s)'))

    def _resolve_administrative_region(self, doc):
        admin_id = (doc.get('administrative_region') or {}).get('administrative_id')
        if not admin_id or not str(admin_id).isdigit():
            return None
        level_id = int(admin_id)
        return AdministrativeLevel.objects.using('mis').filter(id=level_id).first()

    def _resolve_reference(self, Model, ref_doc):
        if not ref_doc or not ref_doc.get('id'):
            return None
        obj, _ = Model.objects.get_or_create(
            legacy_id=ref_doc['id'], defaults={'name': ref_doc.get('name', '')},
        )
        return obj

    def _migrate_issue(self, doc, attachments_mapping):
        administrative_region = self._resolve_administrative_region(doc)
        

        status = self._resolve_reference(IssueStatus, doc.get('status'))
        category = self._resolve_reference(IssueCategory, doc.get('category'))
        issue_type = self._resolve_reference(IssueType, doc.get('issue_type'))
        age_group = self._resolve_reference(IssueAgeGroup, doc.get('citizen_age_group'))
        if status is None or category is None or issue_type is None:
            return None

        assignee_doc = doc.get('assignee') or {}
        reporter_doc = doc.get('reporter') or {}
        administrative_region_doc = doc.get('administrative_region') or {}

        created_date = _dt(doc.get('created_date')) or _dt(doc.get('intake_date'))
        intake_date = _dt(doc.get('intake_date')) or created_date
        issue_date = _dt(doc.get('issue_date')) or created_date

        issue, _created = Issue.objects.update_or_create(
            # internal_code=doc['internal_code'],
            legacy_couch_id=doc.get('_id'),
            defaults=dict(
                # legacy_couch_id=doc.get('_id'),
                internal_code=doc['internal_code'],
                tracking_code=doc.get('tracking_code'),
                auto_increment_id=doc.get('auto_increment_id') or 0,
                description=doc.get('description', ''),
                confirmed=doc.get('confirmed', False),
                citizen=doc.get('citizen'),
                contact_medium=doc.get('contact_medium'),
                citizen_type=str(doc.get('citizen_type')) if doc.get('citizen_type') is not None else None,
                citizen_group_1=doc.get('citizen_group_1'),
                citizen_group_2=doc.get('citizen_group_2'),
                citizen_or_group=doc.get('citizen_or_group'),
                source=doc.get('source') or 'mobile',
                publish=doc.get('publish', False),
                publish_date=_dt(doc.get('publish_date')),
                notification_send=doc.get('notification_send', True),
                ongoing_issue=doc.get('ongoing_issue', False),
                event_recurrence=doc.get('event_recurrence', False),
                resolution_days=doc.get('resolution_days') or 0,
                created_date=created_date,
                intake_date=intake_date,
                issue_date=issue_date,
                resolution_date=_dt(doc.get('resolution_date')),
                reject_date=_dt(doc.get('reject_date')),
                research_result=doc.get('research_result'),
                original_description=doc.get('original_description'),
                status=status,
                category=category,
                age_group=age_group,
                issue_type=issue_type,
                assignee=_user(assignee_doc.get('id')),
                assignee_name=assignee_doc.get('name'),
                reporter=_user(reporter_doc.get('id')),
                reporter_name=reporter_doc.get('name'),
                administrative_region=administrative_region,
                administrative_region_name=administrative_region_doc.get('name'),
                location_info=doc.get('location_info'),
                structure_in_charge=doc.get('structure_in_charge'),
                contact_information=doc.get('contact_information'),
                commune=doc.get('commune'),
                escalate_flag=bool(doc.get('escalate_flag')),
            ),
        )
        return issue

    def _migrate_comments(self, doc, issue):
        for c in doc.get('comments') or []:
            due_at = _dt(c.get('due_at')) or issue.created_date
            Comment.objects.get_or_create(
                issue=issue, comment=c.get('comment', ''), due_at=due_at,
                defaults={'author': _user(c.get('id')), 'author_name': c.get('name', '')},
            )

    def _migrate_status_stories(self, doc, issue):
        for s in doc.get('issue_status_stories') or []:
            status = self._resolve_reference(IssueStatus, s.get('status'))
            if status is None:
                continue
            user_doc = s.get('user') or {}
            datetime_value = _dt(s.get('datetime')) or issue.created_date
            IssueStatusStory.objects.get_or_create(
                issue=issue, datetime=datetime_value, status=status,
                defaults={
                    'user': _user(user_doc.get('id')),
                    'user_full_name': user_doc.get('full_name'),
                    'comment': s.get('comment'),
                    'email_notified': True
                },
            )

    def _migrate_reasons(self, doc, issue, attachments_mapping):
        for r in (doc.get('reasons') or []) + (doc.get('resolution_files') or []):
            attachment = None
            bd_id = r.get('bd_id')
            if bd_id and bd_id in attachments_mapping:
                attachment = Attachment.objects.filter(id=attachments_mapping[bd_id]).first()
                if attachment and attachment.issue_id is None:
                    attachment.issue = issue
                    attachment.save(update_fields=['issue'])

            subject = r.get('subject') or r.get('type') or 'reason'
            due_at = _dt(r.get('due_at'))
            Reason.objects.get_or_create(
                issue=issue, subject=subject, comment=r.get('comment'),
                defaults={
                    'user': _user(r.get('user_id')),
                    'user_name': r.get('user_name'),
                    'due_at': due_at,
                    'attachment': attachment,
                },
            )

    def _migrate_escalation(self, doc, issue, attachments_mapping):
        for r in doc.get('escalation_reasons') or []:
            attachment_doc = r.get('attachment') or {}
            attachment = None
            bd_id = attachment_doc.get('bd_id')
            if bd_id and bd_id in attachments_mapping:
                attachment = Attachment.objects.filter(id=attachments_mapping[bd_id]).first()

            due_at = _dt(r.get('due_at')) or issue.created_date
            EscalationReason.objects.get_or_create(
                issue=issue, due_at=due_at, comment=r.get('comment'),
                defaults={
                    'user': _user(r.get('id')),
                    'user_name': r.get('name'),
                    'attachment': attachment,
                },
            )

        for lvl in doc.get('escalation_administrativelevels') or []:
            escalate_to = lvl.get('escalate_to') or {}
            due_at = _dt(lvl.get('due_at')) or issue.created_date
            admin_id = escalate_to.get('administrative_id')
            EscalationLevel.objects.get_or_create(
                issue=issue, due_at=due_at,
                administrative_level=escalate_to.get('administrative_level'),
                defaults={
                    'administrative_id': int(admin_id) if admin_id and str(admin_id).isdigit() else None,
                    'name': escalate_to.get('name'),
                },
            )
