"""« Plaintes escaladées vers une instance supérieure » de /diagnostics/."""
import pytest
from django.utils import timezone

from dashboard.diagnostics.views import compute_escalation_stats
from dashboard.grm.test_legacy_doc_sync import fake_administrative_level  # noqa: F401
from dashboard.grm.test_resolution_dates import _make_issue, auth_client, statuses  # noqa: F401
from issue.models import EscalationLevel

pytestmark = pytest.mark.django_db


def _escalate(issue, level, deleted=False):
    # Même date pour tous les niveaux, comme dans les données migrées de CouchDB.
    EscalationLevel.objects.create(issue=issue, administrative_level=level, due_at=timezone.now(), is_deleted=deleted)


def test_counts_escalated_issues_by_highest_level_reached(auth_client, statuses):
    user, status = auth_client.user, statuses['initial']
    to_region = _make_issue(user, status)
    _escalate(to_region, 'Region')
    _escalate(to_region, 'Canton')  # enregistré après, mais la Région est plus haute
    to_canton = _make_issue(user, status)
    _escalate(to_canton, 'Canton')
    deleted_only = _make_issue(user, status)
    _escalate(deleted_only, 'Country', deleted=True)  # escalade supprimée : ne compte pas
    not_escalated = _make_issue(user, status)

    stats = compute_escalation_stats([to_region, to_canton, deleted_only, not_escalated])

    assert stats['total'] == 2
    assert stats['percentage'] == 50
    by_level = {line['name']: line['count'] for line in stats['by_level']}
    assert by_level['Canton'] == 1
    assert by_level['Region'] == 1
    assert by_level['National'] == 0
    assert by_level['Commune'] == 0
    assert 'Prefecture' not in by_level  # ancien niveau, vide : masqué


def test_no_issues():
    stats = compute_escalation_stats([])
    assert stats['total'] == 0 and stats['percentage'] == 0
