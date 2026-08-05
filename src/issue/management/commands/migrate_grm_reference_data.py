"""Migre les documents de référence de la base CouchDB `grm` (issue_status, issue_category,
issue_age_group, issue_type, issue_department) vers Postgres. Rejouable sans doublon
(`update_or_create` sur `legacy_id`, l'`id` numérique CouchDB — pas l'`_id` du document).

Usage : python manage.py migrate_grm_reference_data
"""
from django.conf import settings
from django.core.management.base import BaseCommand

from client import get_db
from issue.models import (
    IssueAgeGroup, IssueCategory, IssueCitizenGroup1, IssueCitizenGroup2, IssueDepartment,
    IssueStatus, IssueType,
)

TYPE_TO_MODEL = {
    'issue_status': IssueStatus,
    'issue_category': IssueCategory,
    'issue_age_group': IssueAgeGroup,
    'issue_type': IssueType,
    'issue_department': IssueDepartment,
    'issue_citizen_group_1': IssueCitizenGroup1,
    'issue_citizen_group_2': IssueCitizenGroup2,
}


class Command(BaseCommand):
    help = 'Migre les référentiels issue_status/issue_category/issue_age_group/issue_type/issue_department depuis CouchDB (grm) vers Postgres.'

    def handle(self, *args, **options):
        db = get_db(settings.COUCHDB_GRM_DATABASE)
        counts = {name: 0 for name in TYPE_TO_MODEL}

        for doc in db:
            doc_type = doc.get('type')
            Model = TYPE_TO_MODEL.get(doc_type)
            if Model is None or not doc.get('id'):
                continue

            defaults = {'legacy_id': doc['id'], 'name': doc.get('name', '')}

            if doc_type == 'issue_status':
                defaults.update({
                    'final_status': doc.get('final_status', False),
                    'initial_status': doc.get('initial_status', False),
                    'rejected_status': doc.get('rejected_status', False),
                    'open_status': doc.get('open_status', False),
                    'unresolved_status': doc.get('unresolved_status', False),
                    'eligible_status': doc.get('eligible_status', False),
                    'not_eligible_status': doc.get('not_eligible_status', False),
                })
            elif doc_type == 'issue_category':
                defaults.update({
                    'label': doc.get('label'),
                    'abbreviation': doc.get('abbreviation'),
                    'confidentiality_level': doc.get('confidentiality_level'),
                    'redirection_protocol': doc.get('redirection_protocol'),
                    'assigned_department': doc.get('assigned_department'),
                    'assigned_appeal_department': doc.get('assigned_appeal_department'),
                    'assigned_escalation_department': doc.get('assigned_escalation_department'),
                    'administrative_level': (doc.get('assigned_department') or {}).get('administrative_level'),
                })
            elif doc_type == 'issue_department':
                head = doc.get('head') or {}
                defaults['head_name'] = head.get('name')

            Model.objects.update_or_create(legacy_id=doc['id'], defaults=defaults)
            counts[doc_type] += 1

        for name, count in counts.items():
            self.stdout.write(self.style.SUCCESS(f'{name}: {count} document(s) migré(s)'))
