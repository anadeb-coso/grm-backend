"""Dates de résolution d'une plainte :
- `resolution_date` : date d'enregistrement de la résolution dans l'application (automatique) ;
- `resolution_real_issue_date` : date réelle de la résolution sur le terrain, saisie par
  l'utilisateur dans le formulaire de résolution (web et mobile).
Couvre aussi la commande de rattrapage `backfill_resolution_date`."""
import uuid
from datetime import date, timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from administrativelevels.models import AdministrativeLevel
from dashboard.grm.forms import IssueResearchResultForm
from dashboard.grm.serializers import LegacyIssueDoc
from issue.models import Issue, IssueCategory, IssueStatus, IssueStatusStory, IssueType

# Réutilise le mock de la base `mis` (AdministrativeLevel) du test voisin.
from dashboard.grm.test_legacy_doc_sync import FAKE_REGION_ID, fake_administrative_level  # noqa: F401

pytestmark = pytest.mark.django_db


@pytest.fixture
def auth_client(django_user_model):
    user = django_user_model.objects.create_user(username='agent', email='agent@example.com', password='pass1234')
    client = APIClient()
    resp = client.post('/api/auth/token/', {'username': 'agent', 'password': 'pass1234'})
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
    client.user = user
    return client


@pytest.fixture
def statuses():
    return {
        'initial': IssueStatus.objects.create(name='Enregistrée', initial_status=True),
        'final': IssueStatus.objects.create(name='Résolue', final_status=True),
    }


def _make_issue(reporter, status, **extra):
    now = timezone.now()
    return Issue.objects.create(
        internal_code=f'DRP-TEST-{uuid.uuid4().hex[:8]}', auto_increment_id=1,
        description='x', confirmed=True, source='mobile',
        created_date=now, intake_date=now, issue_date=now,
        status=status,
        category=IssueCategory.objects.create(name='Demande de renseignement'),
        issue_type=IssueType.objects.create(name='Plainte'),
        administrative_region=AdministrativeLevel(id=FAKE_REGION_ID, name='Village Test', type='Village'),
        reporter=reporter, **extra,
    )


def test_resolution_form_requires_real_date_and_refuses_future():
    base = {'research_result': 'Réglé à l’amiable'}
    form = IssueResearchResultForm(data=base)
    form.is_valid()
    assert 'resolution_real_issue_date' in form.errors  # obligatoire

    future = (timezone.localdate() + timedelta(days=1)).isoformat()
    form = IssueResearchResultForm(data={**base, 'resolution_real_issue_date': future})
    form.is_valid()
    assert 'resolution_real_issue_date' in form.errors  # pas dans le futur

    form = IssueResearchResultForm(data={**base, 'resolution_real_issue_date': '2026-10-01'})
    form.is_valid()
    assert 'resolution_real_issue_date' not in form.errors
    assert form.cleaned_data['resolution_real_issue_date'] == date(2026, 10, 1)


def test_web_save_persists_both_resolution_dates(auth_client, statuses):
    issue = _make_issue(auth_client.user, statuses['initial'])
    real = timezone.make_aware(timezone.datetime(2026, 10, 1))

    doc = LegacyIssueDoc(issue)
    doc['resolution_date'] = timezone.now()
    doc['resolution_real_issue_date'] = real
    doc.save()

    issue.refresh_from_db()
    assert issue.resolution_date is not None
    assert issue.resolution_real_issue_date == real
    assert LegacyIssueDoc(issue)['resolution_real_issue_date']  # exposé à la vue legacy


def test_mobile_push_saves_real_resolution_date(auth_client, statuses):
    issue = _make_issue(auth_client.user, statuses['initial'])
    payload = {'changes': {'issues': {'created': [], 'deleted': [], 'updated': [{
        'id': str(issue.pk),
        'status': str(statuses['final'].pk),
        'resolution_date': '2026-11-10T09:00:00.000Z',
        'resolution_real_issue_date': '2026-11-02T00:00:00.000Z',
        '_changed': 'status_id,resolution_date,resolution_real_issue_date',
    }]}}}
    resp = auth_client.post('/api/sync/push/', payload, format='json')
    assert resp.status_code == 204, getattr(resp, 'data', None)

    issue.refresh_from_db()
    assert issue.resolution_date.date() == date(2026, 11, 10)
    assert issue.resolution_real_issue_date.date() == date(2026, 11, 2)

    pulled = auth_client.get('/api/sync/pull/', {'last_pulled_at': 0}).data['changes']['issues']
    rows = pulled['created'] + pulled['updated']
    assert 'resolution_real_issue_date' in rows[0]


def test_backfill_fills_resolution_date_from_status_history(auth_client, statuses):
    with_story = _make_issue(auth_client.user, statuses['final'])
    first = timezone.now() - timedelta(days=10)
    IssueStatusStory.objects.create(issue=with_story, status=statuses['final'], datetime=first)
    IssueStatusStory.objects.create(issue=with_story, status=statuses['final'], datetime=first + timedelta(days=2))
    without_story = _make_issue(auth_client.user, statuses['final'])
    already = _make_issue(auth_client.user, statuses['final'], resolution_date=timezone.now())
    already_value = already.resolution_date

    call_command('backfill_resolution_date', '--dry-run')
    with_story.refresh_from_db()
    assert with_story.resolution_date is None  # dry-run n'écrit rien

    call_command('backfill_resolution_date')
    for obj in (with_story, without_story, already):
        obj.refresh_from_db()
    assert with_story.resolution_date == first  # première résolution de l'historique
    assert with_story.resolution_real_issue_date is None  # jamais devinée
    assert without_story.resolution_date is None
    assert already.resolution_date == already_value  # jamais écrasée
