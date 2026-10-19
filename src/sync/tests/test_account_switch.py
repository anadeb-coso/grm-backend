from datetime import timedelta

import pytest
from django.utils import timezone

from issue.models import Issue
from sync.tests.test_issue_scope import (  # noqa: F401 (fixtures)
    _auth_client, _make_issue, fake_administrative_level, reference_data,
)

# Changement de compte sur un même téléphone (grm-frontend/src/database/sync.js::
# prepareLocalDatabaseOwner) : la table `issues` est filtrée par utilisateur, un pull incrémental
# repris depuis le `last_pulled_at` du compte précédent ne renvoie pas au nouveau compte ses
# plaintes plus anciennes. Le mobile repart donc d'un pull complet (base vidée,
# `last_pulled_at=0`), ou redemande `issues` en entier (`full_tables`) si le propriétaire de la
# base locale est inconnu.
pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def no_pull_side_effects(monkeypatch):
    """Les tâches lancées en fin de pull (notification d'une nouvelle plainte...) modifient les
    plaintes, donc leur `updated_at` : neutralisées pour comparer des pulls à `updated_at` fixe."""
    from sync import views
    for name in (
        'check_issues', 'escalate_issues', 'send_sms_message', 'send_a_new_issue_notification',
        'send_issue_status_notifications', 'send_comment_notifications',
    ):
        # `raising=False` : `send_comment_notifications` n'existe pas dans toutes les versions.
        monkeypatch.setattr(views, name, lambda: None, raising=False)


def _pull_issue_ids(client, **params):
    resp = client.get('/api/sync/pull/', params)
    assert resp.status_code == 200, resp.data
    return {row['id'] for row in resp.data['changes']['issues']['updated']}, resp.data['timestamp']


@pytest.fixture
def switch(django_user_model, reference_data):
    """Un superviseur a une plainte assignée, antérieure à la dernière synchronisation de la
    facilitatrice qui utilisait le téléphone avant lui."""
    facilitator, facilitator_client = _auth_client(django_user_model, 'facilitatrice')
    supervisor, supervisor_client = _auth_client(django_user_model, 'superviseur')
    facilitator_issue = _make_issue(reference_data, 'DRP-FC', reporter=facilitator)
    supervisor_issue = _make_issue(reference_data, 'DRP-SUP', assignee=supervisor)
    # Une minute plus tôt : `last_pulled_at` est arrondi à la milliseconde inférieure, une plainte
    # créée dans la même milliseconde que le pull lui serait sinon postérieure.
    past = timezone.now() - timedelta(minutes=1)
    Issue.objects.filter(pk__in=[facilitator_issue.pk, supervisor_issue.pk]).update(created_at=past, updated_at=past)
    _ids, last_pulled_at = _pull_issue_ids(facilitator_client, last_pulled_at=0)
    return supervisor_client, str(supervisor_issue.id), last_pulled_at


def test_incremental_pull_after_switch_misses_older_issues(switch):
    supervisor_client, supervisor_issue_id, last_pulled_at = switch

    ids, _ = _pull_issue_ids(supervisor_client, last_pulled_at=last_pulled_at)

    assert supervisor_issue_id not in ids


def test_full_pull_after_reset_returns_only_the_new_account_issues(switch):
    supervisor_client, supervisor_issue_id, _ = switch

    ids, _ = _pull_issue_ids(supervisor_client, last_pulled_at=0)

    assert ids == {supervisor_issue_id}


def test_full_tables_issues_returns_older_issues_without_reset(switch):
    supervisor_client, supervisor_issue_id, last_pulled_at = switch

    ids, _ = _pull_issue_ids(
        supervisor_client, last_pulled_at=last_pulled_at, full_tables='issues,phases,tasks,bp_projects,budget_allocations',
    )

    assert ids == {supervisor_issue_id}
