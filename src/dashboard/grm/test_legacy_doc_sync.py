"""Régression : toute écriture faite depuis le dashboard web (`LegacyIssueDoc.save()`) ou par les
tâches d'arrière-plan (`dashboard/tasks.py`) doit rafraîchir `Issue.updated_at`, sinon le pull
incrémental mobile (`sync/views.py::PullView`, qui ne détecte que `updated_at > last_pulled_at`)
ne voit jamais le changement — même après un rafraîchissement manuel côté mobile. Bug réel signalé
par l'utilisateur : des mises à jour faites côté grm-backend (description, statut...) n'arrivaient
jamais côté grm-frontend."""
import uuid

import pytest
from django.db.models import query as query_module
from django.utils import timezone
from rest_framework.test import APIClient

from administrativelevels.models import AdministrativeLevel
from dashboard.grm.serializers import LegacyIssueDoc
from issue.models import Issue, IssueCategory, IssueStatus, IssueType

pytestmark = pytest.mark.django_db

FAKE_REGION_ID = 999002


@pytest.fixture(autouse=True)
def fake_administrative_level(monkeypatch):
    """`AdministrativeLevel` vit dans la base MySQL externe `mis` (non migrée/gérée ici, cf.
    grm/routers.py) : on mocke la résolution de l'unique id utilisé par ces tests plutôt que
    d'ouvrir une vraie connexion `mis` (même pattern que sync/tests/test_sync.py)."""
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
    client.user = user
    return client


@pytest.fixture
def issue(auth_client):
    region = AdministrativeLevel(id=FAKE_REGION_ID, name='Village Test', type='Village')
    status = IssueStatus.objects.create(name='Enregistrée', initial_status=True)
    category = IssueCategory.objects.create(name='Demande de renseignement')
    issue_type = IssueType.objects.create(name='Plainte')
    now = timezone.now()
    return Issue.objects.create(
        internal_code=f'DRP-TEST-{uuid.uuid4().hex[:8]}', auto_increment_id=1,
        description='Description initiale', confirmed=True, source='web',
        created_date=now, intake_date=now, issue_date=now,
        status=status, category=category, issue_type=issue_type, administrative_region=region,
        # Requis depuis le scoping du pull/push (sync/views.py::_issue_visibility_filter/
        # _issue_owned_by) : ce fixture teste la propagation de `updated_at`, pas le scoping —
        # on rend donc l'issue visible/modifiable par `auth_client` en la lui faisant "reporter".
        reporter=auth_client.user,
    )


def test_legacy_doc_save_bumps_updated_at_so_mobile_pull_sees_it(auth_client, issue):
    # Simule un appareil mobile déjà à jour : son `last_pulled_at` est postérieur à la création
    # de l'issue ci-dessus.
    last_pulled_at = int(timezone.now().timestamp() * 1000)

    resp = auth_client.get('/api/sync/pull/', {'last_pulled_at': last_pulled_at})
    assert resp.status_code == 200
    assert resp.data['changes']['issues']['updated'] == []

    # Modification faite depuis le dashboard web, exactement comme dans
    # dashboard/grm/views.py::EditIssueView (`self.doc['description'] = ...; self.doc.save()`).
    doc = LegacyIssueDoc(issue)
    doc['description'] = 'Description modifiée depuis le dashboard'
    doc.save()

    resp2 = auth_client.get('/api/sync/pull/', {'last_pulled_at': last_pulled_at})
    assert resp2.status_code == 200
    updated = resp2.data['changes']['issues']['updated']
    assert len(updated) == 1
    assert updated[0]['id'] == str(issue.pk)
    assert updated[0]['description'] == 'Description modifiée depuis le dashboard'


def test_push_tombstone_bumps_updated_at_so_other_devices_see_the_deletion(auth_client, issue):
    """Un appareil pousse une suppression (`is_deleted=True`) ; un AUTRE appareil, déjà à jour au
    moment de la suppression, doit la voir au pull suivant."""
    last_pulled_at = int(timezone.now().timestamp() * 1000)

    payload = {'changes': {'issues': {'created': [], 'updated': [], 'deleted': [str(issue.pk)]}}}
    resp = auth_client.post('/api/sync/push/', payload, format='json')
    assert resp.status_code == 204, resp.data

    resp2 = auth_client.get('/api/sync/pull/', {'last_pulled_at': last_pulled_at})
    assert resp2.status_code == 200
    assert issue.pk in resp2.data['changes']['issues']['deleted']
