import uuid

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from budgeting.models import BpProject, Phase
from issue.models import Adl

pytestmark = pytest.mark.django_db


def _auth_client(django_user_model, username, email):
    user = django_user_model.objects.create_user(username=username, email=email, password='pass1234')
    client = APIClient()
    resp = client.post('/api/auth/token/', {'username': username, 'password': 'pass1234'})
    assert resp.status_code == 200, resp.data
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
    return user, client


@pytest.fixture
def facilitator_a(django_user_model):
    user, client = _auth_client(django_user_model, 'facilitator_a', 'a@example.com')
    adl = Adl.objects.create(name='ADL A', representative=user)
    return user, client, adl


@pytest.fixture
def facilitator_b(django_user_model):
    user, client = _auth_client(django_user_model, 'facilitator_b', 'b@example.com')
    adl = Adl.objects.create(name='ADL B', representative=user)
    return user, client, adl


def test_push_creates_phase_for_own_adl(facilitator_a):
    _user, client, adl = facilitator_a
    payload = {
        'changes': {
            'phases': {
                'created': [{
                    'id': str(uuid.uuid4()),
                    'adl': str(adl.id),
                    'ordinal': 1,
                    'title': 'Phase 1',
                    'is_deleted': False,
                }],
                'updated': [], 'deleted': [],
            }
        }
    }
    resp = client.post('/api/sync/push/', payload, format='json')
    assert resp.status_code == 204, resp.data
    assert Phase.objects.filter(adl=adl, title='Phase 1').exists()


def test_pull_only_returns_own_phases(facilitator_a, facilitator_b):
    _user_a, client_a, adl_a = facilitator_a
    _user_b, client_b, adl_b = facilitator_b

    Phase.objects.create(adl=adl_a, ordinal=1, title='Phase A')
    Phase.objects.create(adl=adl_b, ordinal=1, title='Phase B')

    # `created` reste toujours vide côté pull (le client mobile est configuré avec
    # `sendCreatedAsUpdated: true`, cf. sync/views.py::PullView) : tout changement non supprimé
    # arrive dans `updated`, qu'il soit nouveau ou modifié.
    resp_a = client_a.get('/api/sync/pull/', {'last_pulled_at': 0})
    titles_a = [p['title'] for p in resp_a.data['changes']['phases']['updated']]
    assert titles_a == ['Phase A']

    resp_b = client_b.get('/api/sync/pull/', {'last_pulled_at': 0})
    titles_b = [p['title'] for p in resp_b.data['changes']['phases']['updated']]
    assert titles_b == ['Phase B']


def test_push_creates_bp_project_and_budget_allocation(facilitator_a):
    _user, client, adl = facilitator_a
    project_id = str(uuid.uuid4())
    now = timezone.now().isoformat()

    payload = {
        'changes': {
            'bp_projects': {
                'created': [{
                    'id': project_id,
                    'adl': str(adl.id),
                    'external_code': 'COMMUNE-1',
                    'subproject_name': 'Forage villageois',
                    'is_deleted': False,
                }],
                'updated': [], 'deleted': [],
            }
        }
    }
    resp = client.post('/api/sync/push/', payload, format='json')
    assert resp.status_code == 204, resp.data
    assert BpProject.objects.filter(id=project_id, subproject_name='Forage villageois').exists()

    payload2 = {
        'changes': {
            'budget_allocations': {
                'created': [{
                    'id': str(uuid.uuid4()),
                    'bp_project': project_id,
                    'description': 'Achat ciment',
                    'amount': '150000.00',
                    'entry_date': now,
                    'is_deleted': False,
                }],
                'updated': [], 'deleted': [],
            }
        }
    }
    resp2 = client.post('/api/sync/push/', payload2, format='json')
    assert resp2.status_code == 204, resp2.data

    resp_pull = client.get('/api/sync/pull/', {'last_pulled_at': 0})
    assert len(resp_pull.data['changes']['bp_projects']['updated']) == 1
    assert len(resp_pull.data['changes']['budget_allocations']['updated']) == 1
