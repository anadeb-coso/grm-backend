import uuid

import pytest
from django.db.models import query as query_module
from django.utils import timezone
from rest_framework.test import APIClient

from administrativelevels.models import AdministrativeLevel
from issue.models import Issue, IssueCategory, IssueStatus, IssueType

# `mis` (MySQL, projet `cosomis`) est une base externe non managée par grm-backend : elle n'a et
# n'aura jamais de migration ici (voir grm/routers.py). Les tests ne doivent donc ni la migrer ni
# la requêter réellement — `fake_administrative_level` mocke `AdministrativeLevel.objects.get()`
# pour un seul id connu, sans jamais ouvrir de connexion vers `mis`.
pytestmark = pytest.mark.django_db

FAKE_REGION_ID = 999001


@pytest.fixture(autouse=True)
def fake_administrative_level(monkeypatch):
    real_get = query_module.QuerySet.get

    def _fake_get(self, *args, **kwargs):
        if self.model is AdministrativeLevel:
            pk = kwargs.get('pk', kwargs.get('id'))
            if pk is not None and int(pk) == FAKE_REGION_ID:
                return AdministrativeLevel(id=FAKE_REGION_ID, name='Village Test', type='Village')
            raise AdministrativeLevel.DoesNotExist()
        return real_get(self, *args, **kwargs)

    monkeypatch.setattr(query_module.QuerySet, 'get', _fake_get)


@pytest.fixture
def auth_client(django_user_model):
    user = django_user_model.objects.create_user(
        username='agent', email='agent@example.com', password='pass1234',
    )
    client = APIClient()
    resp = client.post('/api/auth/token/', {'username': 'agent', 'password': 'pass1234'})
    assert resp.status_code == 200, resp.data
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
    # Exposé pour que les tests puissent poser `reporter`/`assignee` sur les issues qu'ils
    # manipulent — depuis le scoping introduit dans sync/views.py (_issue_visibility_filter/
    # _issue_owned_by, voir sync/tests/test_issue_scope.py), le pull comme le push d'une `Issue`
    # sont restreints à ce que cet utilisateur a enregistré, ce qui lui est assigné, ou ses
    # localités d'intervention — aucune de ces conditions n'est vraie par défaut pour un compte
    # sans `Adl`/`GovernmentWorker` comme celui-ci.
    client.user = user
    return client


@pytest.fixture
def reference_data():
    region = AdministrativeLevel(id=FAKE_REGION_ID, name='Village Test', type='Village')
    return {
        'status': IssueStatus.objects.create(name='Enregistrée', initial_status=True),
        'category': IssueCategory.objects.create(name='Demande de renseignement'),
        'issue_type': IssueType.objects.create(name='Plainte'),
        'region': region,
    }


def _issue_payload(reference_data, **overrides):
    now = timezone.now().isoformat()
    payload = {
        'id': str(uuid.uuid4()),
        'internal_code': f'DRP-TEST-{uuid.uuid4().hex[:8]}',
        'auto_increment_id': 1,
        'description': 'Test création offline',
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
        'administrative_region': reference_data['region'].id,
        'is_deleted': False,
    }
    payload.update(overrides)
    return payload


def test_push_creates_issue(auth_client, reference_data):
    """Un enregistrement créé côté mobile (offline) doit apparaître en base après push."""
    payload = {'changes': {'issues': {
        'created': [_issue_payload(reference_data, reporter=auth_client.user.id)],
        'updated': [], 'deleted': [],
    }}}
    resp = auth_client.post('/api/sync/push/', payload, format='json')
    assert resp.status_code == 204, resp.data
    assert Issue.objects.filter(internal_code=payload['changes']['issues']['created'][0]['internal_code']).exists()


def test_push_rejects_unknown_fk_with_400(auth_client, reference_data):
    """Une FK inexistante (statut, catégorie, niveau administratif...) doit renvoyer un 400
    explicite plutôt qu'une IntegrityError (CLAUDE.md §9)."""
    payload = {
        'changes': {
            'issues': {
                'created': [_issue_payload(reference_data, status=999999, reporter=auth_client.user.id)],
                'updated': [], 'deleted': [],
            }
        }
    }
    resp = auth_client.post('/api/sync/push/', payload, format='json')
    assert resp.status_code == 400


def test_push_rejects_unknown_administrative_region_with_400(auth_client, reference_data):
    """Idem pour la FK cross-db vers `administrativelevels.AdministrativeLevel` (base `mis`)."""
    payload = {
        'changes': {
            'issues': {
                'created': [_issue_payload(
                    reference_data, administrative_region=123456789, reporter=auth_client.user.id,
                )],
                'updated': [], 'deleted': [],
            }
        }
    }
    resp = auth_client.post('/api/sync/push/', payload, format='json')
    assert resp.status_code == 400


def test_push_merges_only_changed_fields(auth_client, reference_data):
    """Le merge champ à champ ne doit toucher que les colonnes listées dans `_changed`, sans
    écraser une colonne modifiée entre-temps côté serveur."""
    now = timezone.now()
    issue = Issue.objects.create(
        internal_code='DRP-TEST-MERGE', auto_increment_id=2, description='Description initiale',
        confirmed=True, source='mobile', created_date=now, intake_date=now, issue_date=now,
        status=reference_data['status'], category=reference_data['category'],
        issue_type=reference_data['issue_type'], administrative_region=reference_data['region'],
        # Requis depuis le scoping du push (_issue_owned_by, sync/views.py) : seul le
        # reporter/assignee de l'issue peut la modifier depuis le mobile.
        reporter=auth_client.user,
    )
    issue.research_result = 'Modifié côté serveur entre-temps'
    issue.save()

    payload = {
        'changes': {
            'issues': {
                'created': [], 'deleted': [],
                'updated': [{
                    'id': str(issue.id),
                    'description': 'Description modifiée hors-ligne',
                    '_changed': 'description',
                }],
            }
        }
    }
    resp = auth_client.post('/api/sync/push/', payload, format='json')
    assert resp.status_code == 204, resp.data

    issue.refresh_from_db()
    assert issue.description == 'Description modifiée hors-ligne'
    assert issue.research_result == 'Modifié côté serveur entre-temps'


def test_pull_returns_changes_since_last_pulled_at(auth_client, reference_data):
    now = timezone.now()
    Issue.objects.create(
        internal_code='DRP-TEST-PULL', auto_increment_id=3, description='Nouvelle plainte',
        confirmed=True, source='web', created_date=now, intake_date=now, issue_date=now,
        status=reference_data['status'], category=reference_data['category'],
        issue_type=reference_data['issue_type'], administrative_region=reference_data['region'],
        # Requis depuis le scoping du pull (_issue_visibility_filter, sync/views.py) : sans
        # localité d'intervention (Adl) ni accès complet, seules les issues enregistrées/
        # assignées à l'utilisateur lui sont diffusées.
        reporter=auth_client.user,
    )
    resp = auth_client.get('/api/sync/pull/', {'last_pulled_at': 0})
    assert resp.status_code == 200
    assert resp.data['force_full_resync'] is False
    # `created` reste toujours vide côté pull (sendCreatedAsUpdated: true côté client, cf.
    # sync/views.py::PullView) : tout changement non supprimé arrive dans `updated`.
    assert len(resp.data['changes']['issues']['updated']) == 1
    assert resp.data['has_more'] is False


def test_pull_forces_full_resync_when_last_pulled_at_too_old(auth_client):
    resp = auth_client.get('/api/sync/pull/', {'last_pulled_at': 1})  # 1970-01-01T00:00:00.001Z
    assert resp.status_code == 200
    assert resp.data['force_full_resync'] is True
    assert resp.data['changes'] == {}


def test_pull_pagination_sets_has_more(auth_client, reference_data):
    from sync.views import PAGE_SIZE
    now = timezone.now()
    for i in range(PAGE_SIZE + 10):
        Issue.objects.create(
            internal_code=f'DRP-TEST-PAGE-{i}', auto_increment_id=100 + i,
            description='x', confirmed=True, source='web', created_date=now,
            intake_date=now, issue_date=now,
            status=reference_data['status'], category=reference_data['category'],
            issue_type=reference_data['issue_type'], administrative_region=reference_data['region'],
            reporter=auth_client.user,
        )
    resp = auth_client.get('/api/sync/pull/', {'last_pulled_at': 0})
    assert resp.data['has_more'] is True
    assert resp.data['cursor'] is not None

    resp2 = auth_client.get('/api/sync/pull/', {'last_pulled_at': 0, 'cursor': resp.data['cursor']})
    assert resp2.status_code == 200
