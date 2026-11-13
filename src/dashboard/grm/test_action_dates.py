"""Dates EXACTES saisies par l'utilisateur (aujourd'hui par défaut, jamais dans le futur) :
acceptation / réouverture d'une plainte et étape d'investigation — web et synchronisation mobile."""
import uuid
from datetime import date, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from administrativelevels.models import AdministrativeLevel
from dashboard.grm.forms import IssueOpenStatusForm, IssueReasonCommentForm
from dashboard.grm.test_legacy_doc_sync import FAKE_REGION_ID, fake_administrative_level  # noqa: F401
from issue.models import (
    Issue, IssueCategory, IssueDepartment, IssueStatus, IssueStatusStory, IssueType, Reason,
)

pytestmark = pytest.mark.django_db
AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}


@pytest.fixture
def agent(django_user_model):
    return django_user_model.objects.create_user(username='agent', email='agent@example.com', password='pass1234')


@pytest.fixture
def issue(agent):
    IssueDepartment.objects.create(legacy_id=1, name='Département')
    now = timezone.now()
    return Issue.objects.create(
        internal_code=f'DRP-{uuid.uuid4().hex[:8]}', auto_increment_id=4242, description='x', confirmed=True,
        source='web', created_date=now, intake_date=now, issue_date=now,
        status=IssueStatus.objects.create(name='Enregistrée', legacy_id=1, initial_status=True),
        category=IssueCategory.objects.create(name='Renseignement', legacy_id=1, assigned_department={'id': 1}),
        issue_type=IssueType.objects.create(name='Plainte', legacy_id=1),
        administrative_region=AdministrativeLevel(id=FAKE_REGION_ID, name='Village Test', type='Village'),
        reporter=agent, assignee=agent,
    )


@pytest.fixture
def open_status():
    return IssueStatus.objects.create(name='En cours de traitement', legacy_id=2, open_status=True)


def _future():
    return (timezone.localdate() + timedelta(days=1)).isoformat()


# --- Formulaires ------------------------------------------------------------------------------

@pytest.mark.parametrize('form_class, field', [
    (IssueOpenStatusForm, 'action_date'),
    (IssueReasonCommentForm, 'investigation_date'),
])
def test_exact_date_defaults_to_today_and_refuses_future(form_class, field):
    form = form_class(initial={})
    assert form.fields[field].initial == timezone.localdate().isoformat()
    assert form.fields[field].widget.attrs['max'] == timezone.localdate().isoformat()

    bad = form_class(data={'open_reason': '', 'reason': 'x', field: _future()}, initial={})
    assert not bad.is_valid() and field in bad.errors
    missing = form_class(data={'open_reason': '', 'reason': 'x'}, initial={})
    assert not missing.is_valid() and field in missing.errors


# --- Web : acceptation / réouverture ---------------------------------------------------------

def test_accept_modal_shows_today_and_saves_exact_date(client, agent, issue, open_status):
    client.force_login(agent)
    url = reverse('dashboard:grm:submit_issue_open_status', kwargs={'issue': issue.auto_increment_id})

    html = client.get(url, **AJAX).content.decode()
    assert 'name="action_date"' in html and f'value="{timezone.localdate().isoformat()}"' in html

    response = client.post(url, {'open_reason': 'Recevable', 'action_date': '2026-11-03'}, **AJAX)
    assert response.status_code == 200
    story = IssueStatusStory.objects.get(issue=issue, status=open_status)
    assert timezone.localtime(story.action_date).date() == date(2026, 11, 3)
    issue.refresh_from_db()
    assert issue.status == open_status


def test_accept_refuses_future_date(client, agent, issue, open_status):
    client.force_login(agent)
    url = reverse('dashboard:grm:submit_issue_open_status', kwargs={'issue': issue.auto_increment_id})
    client.post(url, {'open_reason': '', 'action_date': _future()}, **AJAX)
    assert not IssueStatusStory.objects.filter(issue=issue).exists()


# --- Web : étape d'investigation -------------------------------------------------------------

@pytest.mark.django_db(databases=['default', 'mis'])
def test_issue_detail_shows_investigation_date_with_today(client, agent, issue):
    client.force_login(agent)
    html = client.get(reverse('dashboard:grm:issue_detail', kwargs={'issue': issue.auto_increment_id})).content.decode()
    assert 'name="investigation_date"' in html
    assert f'value="{timezone.localdate().isoformat()}"' in html


def test_investigation_step_saves_exact_date(client, agent, issue):
    client.force_login(agent)
    url = reverse('dashboard:grm:add_comment_to_issue', kwargs={'issue': issue.auto_increment_id}) + '?reason=1'
    response = client.post(url, {'comment': 'Visite du site', 'investigation_date': '2026-11-04'}, **AJAX)
    assert response.status_code == 200

    reason = Reason.objects.get(issue=issue, subject='comment')
    assert timezone.localtime(reason.action_date).date() == date(2026, 11, 4)
    story = IssueStatusStory.objects.get(issue=issue)
    assert timezone.localtime(story.action_date).date() == date(2026, 11, 4)


def test_investigation_step_refuses_future_date(client, agent, issue):
    client.force_login(agent)
    url = reverse('dashboard:grm:add_comment_to_issue', kwargs={'issue': issue.auto_increment_id}) + '?reason=1'
    client.post(url, {'comment': 'Visite', 'investigation_date': _future()}, **AJAX)
    assert not Reason.objects.filter(issue=issue).exists()


def test_plain_comment_does_not_need_investigation_date(client, agent, issue):
    client.force_login(agent)
    url = reverse('dashboard:grm:add_comment_to_issue', kwargs={'issue': issue.auto_increment_id})
    assert client.post(url, {'comment': 'Simple commentaire'}, **AJAX).status_code == 200
    assert issue.comments.filter(comment='Simple commentaire').exists()


# --- Synchronisation mobile ------------------------------------------------------------------

def test_mobile_push_saves_exact_dates(agent, issue, open_status):
    client = APIClient()
    token = client.post('/api/auth/token/', {'username': 'agent', 'password': 'pass1234'}).data['access']
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
    story_id, reason_id = str(uuid.uuid4()), str(uuid.uuid4())
    payload = {'changes': {
        'issue_status_stories': {'created': [], 'deleted': [], 'updated': [{
            'id': story_id, 'issue': str(issue.pk), 'status': str(open_status.pk),
            'datetime': '2026-11-10T08:00:00.000Z', 'action_date': '2026-11-05T00:00:00.000Z', 'is_deleted': False,
        }]},
        'reasons': {'created': [], 'deleted': [], 'updated': [{
            'id': reason_id, 'issue': str(issue.pk), 'subject': 'comment', 'comment': 'Étape',
            'due_at': '2026-11-10T08:00:00.000Z', 'action_date': '2026-11-06T00:00:00.000Z', 'is_deleted': False,
        }]},
    }}
    response = client.post('/api/sync/push/', payload, format='json')
    assert response.status_code == 204, getattr(response, 'data', None)
    assert IssueStatusStory.objects.get(pk=story_id).action_date.date() == date(2026, 11, 5)
    assert Reason.objects.get(pk=reason_id).action_date.date() == date(2026, 11, 6)
