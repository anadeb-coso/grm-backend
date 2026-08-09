import uuid

import pytest
from django.db.models import query as query_module
from django.utils import timezone
from rest_framework.test import APIClient

from administrativelevels.models import AdministrativeLevel
from authentication.models import GovernmentWorker
from issue.models import Adl, Issue, IssueCategory, IssueStatus, IssueType

# Scoping des issues (pull + push) introduit en plus du scoping déjà existant pour le domaine
# "budget participatif" (cf. test_budgeting_sync.py) : un utilisateur mobile ne doit recevoir/
# modifier que les issues de ses localités d'intervention (Adl.*administrative*_ids), celles
# qu'il a enregistrées, et celles qui lui sont assignées — sauf accès complet ("1").
pytestmark = pytest.mark.django_db

IN_SCOPE_REGION_ID = 999101
OUT_OF_SCOPE_REGION_ID = 999102


@pytest.fixture(autouse=True)
def fake_administrative_level(monkeypatch):
    """Même principe que sync/tests/test_sync.py : `mis` (MySQL externe) n'est jamais réellement
    interrogée dans ces tests, seuls les deux ids ci-dessus sont mockés."""
    real_get = query_module.QuerySet.get
    known = {
        IN_SCOPE_REGION_ID: AdministrativeLevel(id=IN_SCOPE_REGION_ID, name='Village Dans Zone', type='Village'),
        OUT_OF_SCOPE_REGION_ID: AdministrativeLevel(id=OUT_OF_SCOPE_REGION_ID, name='Village Hors Zone', type='Village'),
    }

    def _fake_get(self, *args, **kwargs):
        if self.model is AdministrativeLevel:
            pk = kwargs.get('pk', kwargs.get('id'))
            if pk is not None and int(pk) in known:
                return known[int(pk)]
            raise AdministrativeLevel.DoesNotExist()
        return real_get(self, *args, **kwargs)

    monkeypatch.setattr(query_module.QuerySet, 'get', _fake_get)


def _auth_client(django_user_model, username):
    user = django_user_model.objects.create_user(
        username=username, email=f'{username}@example.com', password='pass1234',
    )
    client = APIClient()
    resp = client.post('/api/auth/token/', {'username': username, 'password': 'pass1234'})
    assert resp.status_code == 200, resp.data
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
    return user, client


@pytest.fixture
def reference_data():
    return {
        'status': IssueStatus.objects.create(name='Enregistrée', initial_status=True),
        'category': IssueCategory.objects.create(name='Demande de renseignement'),
        'issue_type': IssueType.objects.create(name='Plainte'),
        'in_scope_region': AdministrativeLevel(id=IN_SCOPE_REGION_ID, name='Village Dans Zone', type='Village'),
        'out_of_scope_region': AdministrativeLevel(id=OUT_OF_SCOPE_REGION_ID, name='Village Hors Zone', type='Village'),
    }


def _make_issue(reference_data, code, region=None, reporter=None, assignee=None):
    now = timezone.now()
    return Issue.objects.create(
        internal_code=code, auto_increment_id=uuid.uuid4().int % 100000, description='Test',
        confirmed=True, source='mobile', created_date=now, intake_date=now, issue_date=now,
        status=reference_data['status'], category=reference_data['category'],
        issue_type=reference_data['issue_type'],
        administrative_region=region or reference_data['out_of_scope_region'],
        reporter=reporter, assignee=assignee,
    )


def _pull_updated_ids(client):
    resp = client.get('/api/sync/pull/', {'last_pulled_at': 0})
    assert resp.status_code == 200, resp.data
    return {row['id'] for row in resp.data['changes']['issues']['updated']}


def _issue_payload(reference_data, **overrides):
    now = timezone.now().isoformat()
    payload = {
        'id': str(uuid.uuid4()),
        'internal_code': f'DRP-SCOPE-{uuid.uuid4().hex[:8]}',
        'auto_increment_id': 1,
        'description': 'Test',
        'confirmed': True,
        'source': 'mobile',
        'publish': False,
        'notification_send': True,
        'ongoing_issue': False,
        'event_recurrence': False,
        'resolution_days': 0,
        'created_date': now,
        'intake_date': now,
        'issue_date': now,
        'status': reference_data['status'].id,
        'category': reference_data['category'].id,
        'issue_type': reference_data['issue_type'].id,
        'administrative_region': reference_data['out_of_scope_region'].id,
        'is_deleted': False,
    }
    payload.update(overrides)
    return payload


# ---- Pull : visibilité par localité / reporter / assignee ----

def test_pull_excludes_issue_outside_scope_and_not_owned(django_user_model, reference_data):
    user, client = _auth_client(django_user_model, 'agent_no_scope')
    Adl.objects.create(name='ADL', representative=user, administrative_region_ids=[IN_SCOPE_REGION_ID])
    issue = _make_issue(reference_data, 'DRP-OUT-1', region=reference_data['out_of_scope_region'])

    assert str(issue.id) not in _pull_updated_ids(client)


@pytest.mark.parametrize('adl_field', [
    'administrative_region_ids',
    'smallest_administrative_level_ids',
    'additional_administrative_region_ids',
    'additional_smallest_administrative_level_ids',
])
def test_pull_includes_issue_in_adl_locality(django_user_model, reference_data, adl_field):
    user, client = _auth_client(django_user_model, f'agent_{adl_field}')
    Adl.objects.create(name='ADL', representative=user, **{adl_field: [IN_SCOPE_REGION_ID]})
    issue = _make_issue(reference_data, f'DRP-IN-{adl_field}', region=reference_data['in_scope_region'])

    assert str(issue.id) in _pull_updated_ids(client)


def test_pull_includes_issue_reported_by_user(django_user_model, reference_data):
    user, client = _auth_client(django_user_model, 'reporter_agent')
    issue = _make_issue(reference_data, 'DRP-REPORTER', reporter=user)

    assert str(issue.id) in _pull_updated_ids(client)


def test_pull_includes_issue_assigned_to_user(django_user_model, reference_data):
    user, client = _auth_client(django_user_model, 'assignee_agent')
    issue = _make_issue(reference_data, 'DRP-ASSIGNEE', assignee=user)

    assert str(issue.id) in _pull_updated_ids(client)


def test_pull_full_access_when_governmentworker_administrative_id_is_1(django_user_model, reference_data):
    user, client = _auth_client(django_user_model, 'national_supervisor')
    GovernmentWorker.objects.create(user=user, department=1, administrative_id='1')
    issue = _make_issue(reference_data, 'DRP-NATIONAL', region=reference_data['out_of_scope_region'])

    assert str(issue.id) in _pull_updated_ids(client)


def test_pull_full_access_when_adl_administrative_region_ids_contains_1(django_user_model, reference_data):
    user, client = _auth_client(django_user_model, 'national_adl')
    Adl.objects.create(name='ADL', representative=user, administrative_region_ids=['1'])
    issue = _make_issue(reference_data, 'DRP-NATIONAL-ADL', region=reference_data['out_of_scope_region'])

    assert str(issue.id) in _pull_updated_ids(client)


# ---- Push : seules les issues enregistrées/assignées à l'utilisateur sont modifiables ----

def test_push_rejects_update_to_issue_not_owned(django_user_model, reference_data):
    _user, client = _auth_client(django_user_model, 'other_agent')
    issue = _make_issue(reference_data, 'DRP-NOT-OWNED')

    payload = {'changes': {'issues': {'created': [], 'deleted': [], 'updated': [{
        'id': str(issue.id), 'description': 'Modifié', '_changed': 'description',
    }]}}}
    resp = client.post('/api/sync/push/', payload, format='json')
    assert resp.status_code == 403


def test_push_accepts_update_to_issue_reported_by_user(django_user_model, reference_data):
    user, client = _auth_client(django_user_model, 'reporter_push_agent')
    issue = _make_issue(reference_data, 'DRP-OWNED-REPORTER', reporter=user)

    payload = {'changes': {'issues': {'created': [], 'deleted': [], 'updated': [{
        'id': str(issue.id), 'description': 'Modifié', '_changed': 'description',
    }]}}}
    resp = client.post('/api/sync/push/', payload, format='json')
    assert resp.status_code == 204, resp.data
    issue.refresh_from_db()
    assert issue.description == 'Modifié'


def test_push_accepts_update_to_issue_assigned_to_user(django_user_model, reference_data):
    user, client = _auth_client(django_user_model, 'assignee_push_agent')
    issue = _make_issue(reference_data, 'DRP-OWNED-ASSIGNEE', assignee=user)

    payload = {'changes': {'issues': {'created': [], 'deleted': [], 'updated': [{
        'id': str(issue.id), 'description': 'Modifié', '_changed': 'description',
    }]}}}
    resp = client.post('/api/sync/push/', payload, format='json')
    assert resp.status_code == 204, resp.data


def test_push_rejects_created_issue_without_reporter_or_assignee_matching_user(django_user_model, reference_data):
    _user, client = _auth_client(django_user_model, 'creator_unowned')
    payload = {'changes': {'issues': {
        'created': [_issue_payload(reference_data)], 'updated': [], 'deleted': [],
    }}}
    resp = client.post('/api/sync/push/', payload, format='json')
    assert resp.status_code == 403


def test_push_accepts_created_issue_with_reporter_matching_user(django_user_model, reference_data):
    user, client = _auth_client(django_user_model, 'creator_owned')
    payload = {'changes': {'issues': {
        'created': [_issue_payload(reference_data, reporter=user.id)], 'updated': [], 'deleted': [],
    }}}
    resp = client.post('/api/sync/push/', payload, format='json')
    assert resp.status_code == 204, resp.data
    assert Issue.objects.filter(id=payload['changes']['issues']['created'][0]['id']).exists()


def test_push_rejects_delete_of_issue_not_owned(django_user_model, reference_data):
    _user, client = _auth_client(django_user_model, 'deleter_unowned')
    issue = _make_issue(reference_data, 'DRP-DELETE-NOT-OWNED')

    payload = {'changes': {'issues': {'created': [], 'updated': [], 'deleted': [str(issue.id)]}}}
    resp = client.post('/api/sync/push/', payload, format='json')
    assert resp.status_code == 403
    issue.refresh_from_db()
    assert issue.is_deleted is False
