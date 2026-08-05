"""Régression : une suppression faite côté serveur (dashboard web ou API) doit être visible du
mobile via le pull incrémental (`sync/views.py::PullView`) — et inversement, une suppression
poussée depuis le mobile doit persister côté serveur. Bugs réels corrigés ici :

1. `PullView` renvoyait TOUJOURS `deleted: []` pour les tables "lecture seule" (`attachments`,
   `adls`, ...) — une suppression de pièce jointe faite depuis le dashboard n'était donc JAMAIS
   vue par le mobile, quel que soit le nombre de rafraîchissements.
2. `IssueAttachmentDeleteView`/`DeleteObjectFormView` faisaient un `.delete()` PHYSIQUE sur des
   modèles synchronisés (`Attachment`, `Reason`, et plus généralement tout `TimestampedSyncModel`)
   — la ligne disparaissait avant qu'un tombstone (`is_deleted=True`) ait pu être calculé à partir
   d'elle, rendant la suppression définitivement invisible côté mobile (même après le correctif
   du point 1, puisqu'il n'y avait plus de ligne du tout pour porter `is_deleted=True`).
3. `attachments` est exclue du protocole `pull`/`push` JSON (flux fichier séparé, CLAUDE.md §3.7)
   — une suppression locale mobile (`record.markAsDeleted()`) n'atteignait donc jamais le serveur.
   Nouveau endpoint dédié `AttachmentDeleteView` (symétrique de l'upload) pour la propager."""
import uuid
from unittest import mock

import pytest
from django.contrib.auth.models import Group
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.files.base import ContentFile
from django.db.models import query as query_module
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from administrativelevels.models import AdministrativeLevel
from authentication.tests import UserFactory
from dashboard.grm.serializers import issue_to_legacy_dict
from grm.tests import DashboardTestCase
from issue.models import Attachment, Comment, Issue, IssueCategory, IssueStatus, IssueType

pytestmark = pytest.mark.django_db

FAKE_REGION_ID = 999003


@pytest.fixture(autouse=True)
def fake_administrative_level(monkeypatch):
    """cf. sync/tests/test_sync.py — `mis` (MySQL externe) n'est jamais réellement interrogée."""
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
    return client


@pytest.fixture
def issue():
    region = AdministrativeLevel(id=FAKE_REGION_ID, name='Village Test', type='Village')
    status = IssueStatus.objects.create(name='Enregistrée', initial_status=True)
    category = IssueCategory.objects.create(name='Demande de renseignement', abbreviation='DRP')
    issue_type = IssueType.objects.create(name='Plainte')
    now = timezone.now()
    return Issue.objects.create(
        internal_code=f'DRP-TEST-{uuid.uuid4().hex[:8]}', auto_increment_id=1,
        description='Description initiale', confirmed=True, source='web',
        created_date=now, intake_date=now, issue_date=now,
        status=status, category=category, issue_type=issue_type, administrative_region=region,
    )


@pytest.fixture
def attachment(issue, settings, tmp_path):
    settings.DEFAULT_FILE_STORAGE = 'django.core.files.storage.FileSystemStorage'
    settings.MEDIA_ROOT = str(tmp_path)
    return Attachment.objects.create(
        issue=issue, file=ContentFile(b'test-bytes', name='piece.pdf'),
        file_name='piece.pdf', content_type='application/pdf', size=10,
    )


def test_pull_surfaces_deletion_of_a_readonly_synced_table(auth_client, attachment):
    """`attachments` est en lecture seule côté push (cf. SYNC_READONLY_MODELS) mais DOIT quand
    même remonter ses suppressions au pull."""
    last_pulled_at = int(timezone.now().timestamp() * 1000)

    resp = auth_client.get('/api/sync/pull/', {'last_pulled_at': last_pulled_at})
    assert resp.status_code == 200
    assert resp.data['changes']['attachments']['deleted'] == []

    attachment.is_deleted = True
    attachment.save(update_fields=['is_deleted', 'updated_at'])

    resp2 = auth_client.get('/api/sync/pull/', {'last_pulled_at': last_pulled_at})
    assert resp2.status_code == 200
    assert attachment.pk in resp2.data['changes']['attachments']['deleted']


def test_attachment_delete_endpoint_soft_deletes_and_is_visible_to_pull(auth_client, attachment):
    """Symétrique de l'upload (`AttachmentUploadView`) : une suppression mobile d'une pièce
    jointe déjà envoyée doit passer par ce endpoint pour atteindre le serveur, `attachments`
    n'étant pas poussée par le protocole `pull`/`push` habituel."""
    last_pulled_at = int(timezone.now().timestamp() * 1000)

    resp = auth_client.delete(f'/api/attachments/{attachment.pk}/')
    assert resp.status_code == 204

    attachment.refresh_from_db()
    assert attachment.is_deleted is True

    resp2 = auth_client.get('/api/sync/pull/', {'last_pulled_at': last_pulled_at})
    assert attachment.pk in resp2.data['changes']['attachments']['deleted']


def test_attachment_delete_endpoint_404_for_unknown_id(auth_client):
    resp = auth_client.delete(f'/api/attachments/{uuid.uuid4()}/')
    assert resp.status_code == 404


class TestIssueAttachmentDeleteView(DashboardTestCase):
    """Vues du dashboard web : authentification par session (pas JWT), cf. grm/tests.py."""

    def setUp(self):
        super().setUp()
        self.region = AdministrativeLevel(id=FAKE_REGION_ID + 1, name='Village Test 2', type='Village')
        self.status = IssueStatus.objects.create(name='Enregistrée', initial_status=True)
        self.category = IssueCategory.objects.create(name='Demande de renseignement', abbreviation='DRP')
        self.issue_type = IssueType.objects.create(name='Plainte')
        now = timezone.now()
        self.issue = Issue.objects.create(
            internal_code=f'DRP-TEST-{uuid.uuid4().hex[:8]}', auto_increment_id=42,
            description='Description initiale', confirmed=True, source='web',
            created_date=now, intake_date=now, issue_date=now,
            status=self.status, category=self.category, issue_type=self.issue_type,
            administrative_region=self.region,
        )
        self.attachment = Attachment.objects.create(
            issue=self.issue, file=ContentFile(b'test-bytes', name='piece.pdf'),
            file_name='piece.pdf', content_type='application/pdf', size=10,
        )
        # `IssueMixin.check_permissions`/`specific_permissions` : appartenir au groupe "Admin"
        # suffit à satisfaire les deux vérifications.
        self.admin_group, _ = Group.objects.get_or_create(name='Admin')
        self.user = UserFactory()
        self.user.groups.add(self.admin_group)

    def test_delete_soft_deletes_attachment_instead_of_hard_deleting(self):
        real_get = query_module.QuerySet.get
        region = self.region

        def _fake_get(qs_self, *args, **kwargs):
            if qs_self.model is AdministrativeLevel:
                pk = kwargs.get('pk', kwargs.get('id'))
                if pk is not None and int(pk) == region.id:
                    return region
                raise AdministrativeLevel.DoesNotExist()
            return real_get(qs_self, *args, **kwargs)

        url = reverse(
            'dashboard:grm:delete_issue_attachment',
            kwargs={'issue': self.issue.auto_increment_id, 'attachment': str(self.attachment.pk)},
        )

        with mock.patch.object(query_module.QuerySet, 'get', _fake_get):
            response = self.delete(url, user=self.user, ajax=True)

        assert response.status_code == 200
        self.attachment.refresh_from_db()  # lève DoesNotExist si la ligne a été physiquement supprimée
        assert self.attachment.is_deleted is True

        # Ne doit plus apparaître dans la vue "legacy" utilisée par les templates du dashboard.
        self.issue.refresh_from_db()
        legacy = issue_to_legacy_dict(self.issue)
        assert all(a['id'] != str(self.attachment.pk) for a in legacy['attachments'])


def _view_with_fake_request():
    """`DeleteObjectFormView._delete_object` utilise `self.request` (messages framework) — non
    testé ici via l'URL/dispatch complet (cf. docstring du test ci-dessous), donc fabriqué à la
    main avec `RequestFactory` + le stockage de messages, comme le ferait le middleware réel."""
    from dashboard.general.views import DeleteObjectFormView

    request = RequestFactory().post('/fake-delete-object-url/')
    request.session = {}
    request._messages = FallbackStorage(request)

    view = DeleteObjectFormView()
    view.request = request
    return view


def test_delete_object_form_view_soft_deletes_synced_models_instead_of_hard_deleting(issue):
    """`DeleteObjectFormView._delete_object` — branche générique (tout modèle autre que `Issue`).
    Testée directement (sans passer par l'URL/dispatch complet) : la route existante
    (`<int:object_id>/<str:type>/`) n'est aujourd'hui construite par aucun template pour un type
    autre que `Issue` (les autres modèles synchronisés ont tous une pk UUID, incompatible avec ce
    convertisseur `<int:...>`) — mais le correctif doit rester correct si/quand cette branche
    devient atteignable pour un modèle synchronisé (Comment, Reason, Adl, Phase, Task...)."""
    now = timezone.now()
    comment = Comment.objects.create(
        issue=issue, author_name='Agent', comment='Un commentaire', due_at=now,
    )

    _view_with_fake_request()._delete_object(comment)

    comment.refresh_from_db()  # lève DoesNotExist si la ligne a été physiquement supprimée
    assert comment.is_deleted is True


def test_delete_object_form_view_still_hard_deletes_non_synced_models():
    """Les modèles jamais synchronisés (pas de `is_deleted`/`updated_at`) gardent le comportement
    d'origine — pas de régression sur le chemin générique existant."""
    group = Group.objects.create(name=f'test-group-{uuid.uuid4().hex[:8]}')
    group_id = group.pk

    _view_with_fake_request()._delete_object(group)

    assert not Group.objects.filter(pk=group_id).exists()
