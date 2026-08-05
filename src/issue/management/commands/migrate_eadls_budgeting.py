"""Migre les champs `phases`/`bp_projects` des documents CouchDB `adl` (base `eadls`) vers
Postgres (`budgeting.Phase`/`Task`/`BpProject`/`BudgetAllocationEntry`). Prérequis : avoir
exécuté `migrate_eadls` avant (les `issue.Adl` correspondants doivent déjà exister).

Aucun exemple de `phases`/`bp_projects` non vide n'existe dans context/example_datas.txt (voir
la revue du domaine budget participatif) — le mapping ci-dessous est déduit de la lecture des
écrans frontend (PhaseTasks, RegisterSubprojects, RegisterVotesActivity, BudgetAllocation,
DocumentTask), pas d'un exemple de document réel. Rejouable : `get_or_create` sur des clés
naturelles (ordinal de phase/tâche, `external_code` de sous-projet).

Usage : python manage.py migrate_eadls_budgeting
"""
from django.conf import settings
from django.utils.dateparse import parse_datetime

from django.core.management.base import BaseCommand

from budgeting.models import BpProject, BudgetAllocationEntry, Phase, Task
from client import get_db
from issue.models import Adl


def _dt(value):
    if not value:
        return None
    if isinstance(value, (int, float)):
        # moment().valueOf() côté client peut être stocké en epoch ms sur `closed_at`.
        from datetime import datetime, timezone
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
    return parse_datetime(value)


class Command(BaseCommand):
    help = "Migre les phases/tâches/sous-projets/budget du budget participatif depuis CouchDB (eadls) vers Postgres."

    def handle(self, *args, **options):
        db = get_db(settings.COUCHDB_DATABASE)  # 'eadls'

        phases_count = tasks_count = projects_count = budget_count = 0

        for doc in db:
            if doc.get('type') != 'adl':
                continue

            adl = Adl.objects.filter(legacy_couch_id=doc['_id']).first()
            if adl is None:
                continue  # facilitateur pas encore migré (migrate_eadls) ou sans email

            for phase_doc in doc.get('phases') or []:
                phase, _ = Phase.objects.get_or_create(
                    adl=adl, ordinal=phase_doc.get('ordinal', 0),
                    defaults={
                        'title': phase_doc.get('title', ''),
                        'open_at': _dt(phase_doc.get('open_at')),
                        'due_at': _dt(phase_doc.get('due_at')),
                        'closed_at': _dt(phase_doc.get('closed_at')),
                    },
                )
                phases_count += 1

                for i, task_doc in enumerate(phase_doc.get('tasks') or []):
                    Task.objects.get_or_create(
                        phase=phase, ordinal=i,
                        defaults={
                            'task_type': task_doc.get('type') or Task.TYPE_DOCUMENT,
                            'title': task_doc.get('title', ''),
                            'description': task_doc.get('description'),
                            'status': task_doc.get('status') or Task.STATUS_NOT_STARTED,
                            'notes': task_doc.get('notes'),
                            'open_at': _dt(task_doc.get('open_at')),
                            'due_at': _dt(task_doc.get('due_at')),
                            'closed_at': _dt(task_doc.get('closed_at')),
                            'location': task_doc.get('location'),
                            'bp_amount': task_doc.get('bp_amount'),
                        },
                    )
                    tasks_count += 1

            for project_doc in doc.get('bp_projects') or []:
                project, _ = BpProject.objects.get_or_create(
                    adl=adl, external_code=project_doc.get('id'),
                    defaults={
                        'district_name': project_doc.get('district_name'),
                        'subproject_name': project_doc.get('subproject_name'),
                        'subproject_description': project_doc.get('subproject_description'),
                        'vote_ym': project_doc.get('vote_ym') or 0,
                        'vote_yf': project_doc.get('vote_yf') or 0,
                        'vote_mm': project_doc.get('vote_mm') or 0,
                        'vote_mf': project_doc.get('vote_mf') or 0,
                        'vote_om': project_doc.get('vote_om') or 0,
                        'vote_of': project_doc.get('vote_of') or 0,
                    },
                )
                projects_count += 1

                for entry_doc in project_doc.get('budget_allocated') or []:
                    BudgetAllocationEntry.objects.get_or_create(
                        bp_project=project,
                        entry_date=_dt(entry_doc.get('timestamp')) or project.created_at,
                        amount=entry_doc.get('amount') or 0,
                        defaults={'description': entry_doc.get('description')},
                    )
                    budget_count += 1

        self.stdout.write(self.style.SUCCESS(
            f'budgeting: {phases_count} phases, {tasks_count} tâches, '
            f'{projects_count} sous-projets, {budget_count} entrées de budget migrées'
        ))
