import uuid

import pytest
from django.db.models import query as query_module
from django.utils import timezone
from rest_framework.test import APIClient

from administrativelevels.models import AdministrativeLevel
from issue.models import Attachment, Issue, IssueCategory, IssueStatus, IssueType

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


def test_push_retries_created_record_that_already_exists_server_side(auth_client, reference_data):
    """Reproduit le 400 rapporte sur `created` (corps 118 octets) : le mobile garde `_status:
    'created'` en local tant qu'un push n'a pas ete confirme comme reussi de son point de vue, et
    retente donc le MEME enregistrement via le bucket `created` a chaque cycle. Si une tentative
    precedente a deja fait exister la ligne cote serveur (meme id), `Serializer(data=record)` sans
    `instance=` declenche le `UniqueValidator` automatique de DRF sur `internal_code` (unique=True)
    — qui ne sait pas qu'il doit exclure CETTE MEME ligne de la verification — et rejette le lot en
    boucle indefiniment, alors qu'il s'agit du meme enregistrement, deja present avec le meme id."""
    payload = {'changes': {'issues': {
        'created': [_issue_payload(reference_data, reporter=auth_client.user.id)],
        'updated': [], 'deleted': [],
    }}}
    record = payload['changes']['issues']['created'][0]

    resp1 = auth_client.post('/api/sync/push/', payload, format='json')
    assert resp1.status_code == 204, resp1.data

    # Le mobile n'a jamais vu ce succes (ex. une AUTRE table du meme lot avait echoue avant le
    # correctif de la transaction separee) : il retente le MEME enregistrement `created`.
    resp2 = auth_client.post('/api/sync/push/', payload, format='json')
    assert resp2.status_code == 204, resp2.data
    assert Issue.objects.filter(id=record['id']).count() == 1


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


def test_push_real_device_created_as_updated_issue_record(auth_client, reference_data):
    """Rejoue tel quel un `record` capture sur un vrai appareil (issue jamais encore synchronisee
    avec succes, `_status: 'created'`, envoyee dans `updated` via `sendCreatedAsUpdated`), avec
    uniquement les FK substituees par des ids resolubles dans l'environnement de test."""
    real_record = {
        'id': '0617c7b5-66df-4b72-8885-bded48944413', '_status': 'created',
        '_changed': 'updated_at,status,escalate_flag',
        'internal_code': 'DRP-1787618390091-702', 'tracking_code': 'house702',
        'auto_increment_id': 18390092, 'description': 'test test test test', 'confirmed': True,
        'citizen': '', 'contact_medium': 'facilitator', 'citizen_type': None,
        'citizen_group_1': None, 'citizen_group_2': None, 'citizen_or_group': None,
        'source': 'mobile', 'publish': False, 'publish_date': None, 'notification_send': True,
        'ongoing_issue': False, 'event_recurrence': False, 'resolution_days': 0,
        'created_date': '2026-08-25T00:39:50.092Z', 'intake_date': '2026-08-25T00:39:50.092Z',
        'issue_date': '2026-08-25T00:39:26.606Z', 'resolution_date': None, 'reject_date': None,
        'research_result': None,
        'status': str(reference_data['status'].id),
        'category': str(reference_data['category'].id),
        'age_group': None,
        'issue_type': str(reference_data['issue_type'].id),
        'assignee': auth_client.user.id, 'assignee_name': 'Vincent ADABOUNOU',
        'reporter': auth_client.user.id, 'reporter_name': 'Vincent ADABOUNOU',
        'administrative_region': FAKE_REGION_ID, 'administrative_region_name': 'ADINA',
        'location_info': '{"issue_location":{"administrative_id":"6755","name":"ADINA"},"location_description":""}',
        'structure_in_charge': '{"name":"Comité de gestion de plaintes","phone":"","email":""}',
        'contact_information': '{"type":"email","contact":""}',
        'commune': '{"name":"Pays","prefecture":""}',
        'escalate_flag': True, 'is_deleted': False,
        'created_at': 1787637595418, 'updated_at': 1787618420556,
    }
    payload = {'changes': {'issues': {'created': [], 'deleted': [], 'updated': [real_record]}}}
    resp = auth_client.post('/api/sync/push/', payload, format='json')
    assert resp.status_code == 204, resp.data
    assert Issue.objects.filter(id=real_record['id'], escalate_flag=True).exists()


def test_push_updates_issue_without_changed_metadata_and_partial_fields(auth_client, reference_data):
    """Reproduit l'erreur rapportee ("This field is required." sur `status`, corps ~79 octets) :
    un enregistrement `issues.updated` sans `_changed` et ne portant QUE les colonnes reellement
    modifiees (`escalate_flag`) — pas `status`/`category`/`issue_type`/`administrative_region`,
    deja valides cote serveur sur l'instance existante. `_merge_update` retombait, faute de
    `_changed`, sur une validation COMPLETE (`Serializer(instance, data=record)` sans
    `partial=True`) qui exige TOUS les champs `required=True` du serializer, meme deja presents
    sur l'instance — echouant des qu'un seul champ change reellement est envoye seul."""
    now = timezone.now()
    issue = Issue.objects.create(
        internal_code='DRP-TEST-NOCHANGED', auto_increment_id=13, description='Test',
        confirmed=True, source='mobile', created_date=now, intake_date=now, issue_date=now,
        status=reference_data['status'], category=reference_data['category'],
        issue_type=reference_data['issue_type'], administrative_region=reference_data['region'],
        reporter=auth_client.user, assignee=auth_client.user,
    )

    payload = {
        'changes': {
            'issues': {
                'created': [], 'deleted': [],
                'updated': [{
                    'id': str(issue.id),
                    'escalate_flag': True,
                    # Pas de `_changed`, pas de `status`/`category`/`issue_type`/
                    # `administrative_region` — seul le champ reellement modifie est envoye.
                }],
            },
        },
    }
    resp = auth_client.post('/api/sync/push/', payload, format='json')
    assert resp.status_code == 204, resp.data

    issue.refresh_from_db()
    assert issue.escalate_flag is True
    # Les champs non envoyes (deja valides sur l'instance) doivent rester intacts.
    assert issue.status_id == reference_data['status'].id


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


# --- Reproduction du 400 observé en conditions réelles sur escalade (village -> canton -> ...) ---
# Reproduit le lot exact poussé par escalateIssue() (grm-frontend/Content.js) : mise à jour de
# `issues` (escalate_flag/status) + nouvelles lignes `escalation_levels`/`reasons`/`escalation_reasons`
# jamais encore synchronisées. Avec `sendCreatedAsUpdated: true` (sync.js), TOUTES ces nouvelles
# lignes arrivent dans `updated`, pas `created` (cf. docstring PullView/PushView) : `_merge_update`
# ne trouvant pas d'instance existante retombe sur une validation COMPLETE (pas de `partial=True`).

def _escalation_push_payload(issue, reference_data, auth_client, escalation_level_id,
                              reason_id, attachment_id):
    now = timezone.now().isoformat()
    return {
        'changes': {
            'issues': {
                'created': [], 'deleted': [],
                'updated': [{
                    'id': str(issue.id),
                    'escalate_flag': True,
                    'status': reference_data['status'].id,
                    '_changed': 'escalate_flag,status',
                }],
            },
            'escalation_levels': {
                'created': [], 'deleted': [],
                'updated': [{
                    'id': str(escalation_level_id),
                    'issue': str(issue.id),
                    'administrative_level': 'Canton',
                    'administrative_id': None,
                    'name': 'Canton Test',
                    'due_at': now,
                    'is_deleted': False,
                    # Pas de `_changed` : c'est une création envoyée comme "updated"
                    # (sendCreatedAsUpdated), comme le ferait réellement WatermelonDB.
                }],
            },
            'reasons': {
                'created': [], 'deleted': [],
                'updated': [{
                    'id': str(reason_id),
                    'issue': str(issue.id),
                    'subject': 'escalation',
                    'user': auth_client.user.id,
                    'user_name': 'Agent Test',
                    'due_at': now,
                    'attachment': str(attachment_id),
                    'is_deleted': False,
                }],
            },
        },
    }


def test_push_escalation_still_commits_issue_when_reason_attachment_not_yet_uploaded(auth_client, reference_data):
    """Reproduit le scenario rapporte : au moment de l'escalade, `reasons` (subject='escalation')
    reference un `attachment_id` dont l'upload (endpoint HTTP separe /api/attachments/) n'a pas
    encore ete confirme cote serveur au moment du push JSON — `reasons` echoue donc sa validation
    (FK inexistante). `issues` (escalate_flag/status) est desormais committee dans SA PROPRE
    transaction (PushView.post) : son echec sur une AUTRE table ne doit plus l'annuler, sinon
    l'issue ne peut jamais atteindre le serveur, la piece jointe ne peut jamais s'y rattacher (son
    upload depend de l'existence de l'issue), et `reasons` ne peut donc jamais se pousser a son
    tour — un verrou mutuel permanent, reproduit a l'identique a chaque cycle de sync (~30s)."""
    now = timezone.now()
    issue = Issue.objects.create(
        internal_code='DRP-TEST-ESCALATE', auto_increment_id=10, description='Test escalade',
        confirmed=True, source='mobile', created_date=now, intake_date=now, issue_date=now,
        status=reference_data['status'], category=reference_data['category'],
        issue_type=reference_data['issue_type'], administrative_region=reference_data['region'],
        reporter=auth_client.user, assignee=auth_client.user,
    )
    dangling_attachment_id = uuid.uuid4()  # jamais cree cote serveur

    payload = _escalation_push_payload(
        issue, reference_data, auth_client,
        escalation_level_id=uuid.uuid4(), reason_id=uuid.uuid4(),
        attachment_id=dangling_attachment_id,
    )
    resp = auth_client.post('/api/sync/push/', payload, format='json')

    # Le lot entier reste rapporte en echec (le client mobile doit reessayer `reasons`), mais
    # `issues` — validee independamment — est bien passee cote serveur.
    assert resp.status_code == 400
    issue.refresh_from_db()
    assert issue.escalate_flag is True


def test_push_escalation_self_heals_once_attachment_uploaded_on_next_cycle(auth_client, reference_data):
    """Suite du scenario precedent : une fois l'issue commitee (cycle N), l'upload de la piece
    jointe (desormais capable de resoudre `issue_id`) reussit, et le push de `reasons` au cycle
    N+1 (meme payload, attachment desormais existant) doit reussir sans intervention manuelle —
    confirmant que le verrou mutuel se resout tout seul en au plus un cycle de sync
    supplementaire."""
    now = timezone.now()
    issue = Issue.objects.create(
        internal_code='DRP-TEST-ESCALATE-HEAL', auto_increment_id=12, description='Test escalade',
        confirmed=True, source='mobile', created_date=now, intake_date=now, issue_date=now,
        status=reference_data['status'], category=reference_data['category'],
        issue_type=reference_data['issue_type'], administrative_region=reference_data['region'],
        reporter=auth_client.user, assignee=auth_client.user,
    )
    escalation_level_id, reason_id = uuid.uuid4(), uuid.uuid4()
    attachment_id = uuid.uuid4()

    # Cycle N : l'attachment n'existe pas encore -> `reasons` echoue, `issues` passe quand meme.
    payload = _escalation_push_payload(
        issue, reference_data, auth_client,
        escalation_level_id=escalation_level_id, reason_id=reason_id, attachment_id=attachment_id,
    )
    resp = auth_client.post('/api/sync/push/', payload, format='json')
    assert resp.status_code == 400
    issue.refresh_from_db()
    assert issue.escalate_flag is True

    # Entre les deux cycles : l'issue existe desormais cote serveur -> l'upload de la piece
    # jointe (POST /api/attachments/, hors du protocole pull/push) peut reussir a son tour.
    Attachment.objects.create(
        id=attachment_id, issue=issue, file_name='pv.pdf', content_type='application/pdf', size=10,
    )

    # Cycle N+1 : meme payload (WatermelonDB retente le meme lot en attente) -> succes complet.
    resp2 = auth_client.post('/api/sync/push/', payload, format='json')
    assert resp2.status_code == 204, resp2.data


def test_push_escalation_reason_with_already_uploaded_attachment_succeeds(auth_client, reference_data):
    """Meme lot, mais l'attachment existe deja cote serveur (upload /api/attachments/ suppose
    deja termine avant le push JSON, ordre normalement garanti par sync.js). Doit reussir."""
    now = timezone.now()
    issue = Issue.objects.create(
        internal_code='DRP-TEST-ESCALATE-2', auto_increment_id=11, description='Test escalade',
        confirmed=True, source='mobile', created_date=now, intake_date=now, issue_date=now,
        status=reference_data['status'], category=reference_data['category'],
        issue_type=reference_data['issue_type'], administrative_region=reference_data['region'],
        reporter=auth_client.user, assignee=auth_client.user,
    )
    attachment = Attachment.objects.create(
        issue=issue, file_name='pv.pdf', content_type='application/pdf', size=10,
    )

    payload = _escalation_push_payload(
        issue, reference_data, auth_client,
        escalation_level_id=uuid.uuid4(), reason_id=uuid.uuid4(),
        attachment_id=attachment.id,
    )
    resp = auth_client.post('/api/sync/push/', payload, format='json')
    assert resp.status_code == 204, resp.data

    issue.refresh_from_db()
    assert issue.escalate_flag is True
