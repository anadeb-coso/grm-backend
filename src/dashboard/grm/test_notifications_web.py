"""Dashboard web : l'assigné traite son issue comme sur le mobile (détail même non publiée,
preuves), commentaires avec options de notification, et cloche des notifications."""
import uuid
from datetime import timedelta

import pytest
from django.contrib.auth.models import Group
from django.core import mail
from django.db.models import query as query_module
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from administrativelevels.models import AdministrativeLevel
from dashboard.grm.functions import build_issue_queryset
from issue import notifications
from issue.models import (
    Comment, Issue, IssueCategory, IssueDepartment, IssueNotification, IssueReadState, IssueStatus,
    IssueType, NotificationBaseline,
)

pytestmark = pytest.mark.django_db

FAKE_REGION_ID = 999012
AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}


@pytest.fixture(autouse=True)
def isolate_external_calls(monkeypatch):
    """`mis` n'est jamais interrogée (cf. sync/tests/test_sync.py), et les tâches d'envoi lancées
    par les pages du dashboard (SMS, escalades, emails de statut) sont hors sujet ici."""
    real_get = query_module.QuerySet.get

    def _fake_get(self, *args, **kwargs):
        if self.model is AdministrativeLevel:
            pk = kwargs.get('pk', kwargs.get('id'))
            if pk is not None and int(pk) == FAKE_REGION_ID:
                return AdministrativeLevel(id=FAKE_REGION_ID, name='Village Test', type='Village')
            raise AdministrativeLevel.DoesNotExist()
        return real_get(self, *args, **kwargs)

    monkeypatch.setattr(query_module.QuerySet, 'get', _fake_get)
    from dashboard.grm import views
    for name in ('escalate_issues', 'send_a_new_issue_notification', 'send_issue_status_notifications'):
        monkeypatch.setattr(views, name, lambda: None)


def _user(django_user_model, name, groups=()):
    user = django_user_model.objects.create_user(
        username=name, email=f'{name}@example.com', password='pass1234', first_name=name.title(),
    )
    for group in groups:
        user.groups.add(Group.objects.get_or_create(name=group)[0])
    return user


@pytest.fixture
def people(django_user_model):
    return {
        'assignee': _user(django_user_model, 'assignee'),
        'other': _user(django_user_model, 'other'),
        'chosen': _user(django_user_model, 'chosen'),
        'admin': _user(django_user_model, 'admin', groups=['Admin']),
    }


@pytest.fixture
def references():
    IssueDepartment.objects.create(legacy_id=5, name='Département test')
    return {
        'registered': IssueStatus.objects.create(name='Enregistrée', initial_status=True),
        'in_progress': IssueStatus.objects.create(name='En cours de traitement'),
        'category': IssueCategory.objects.create(name='Infrastructures', assigned_department={'id': 5}),
        'issue_type': IssueType.objects.create(name='Plainte'),
    }


def _issue(references, number, assignee=None, publish=False, status='registered'):
    now = timezone.now()
    return Issue.objects.create(
        internal_code=f'DRP-WEB-{uuid.uuid4().hex[:8]}', tracking_code='Car7', auto_increment_id=number,
        description='Route impraticable', confirmed=True, source='web', publish=publish,
        notification_send=True, created_date=now, intake_date=now, issue_date=now,
        status=references[status], category=references['category'], issue_type=references['issue_type'],
        administrative_region=AdministrativeLevel(id=FAKE_REGION_ID, name='Village Test', type='Village'),
        administrative_region_name='Village Test',
        assignee=assignee, assignee_name=assignee.name if assignee else None,
    )


def _unread_comment_for(user, issue, author):
    comment = Comment.objects.create(
        issue=issue, author=author, author_name=author.name, comment='À vérifier', due_at=timezone.now(),
        is_user_comment=True,
    )
    return IssueNotification.objects.create(
        recipient=user, issue=issue, comment=comment, issue_code=issue.internal_code, comment_text='À vérifier',
    )


@pytest.mark.django_db(databases=['default', 'mis'])
def test_assignee_opens_unpublished_issue_which_becomes_read(client, people, references):
    # Le rendu complet de la page lit le village dans `mis` (base de test `test_grm_mis`).
    AdministrativeLevel.objects.using('mis').create(id=FAKE_REGION_ID, name='Village Test', type='Village')
    issue = _issue(references, 101, assignee=people['assignee'], publish=False)
    notification = _unread_comment_for(people['assignee'], issue, people['other'])
    client.force_login(people['assignee'])

    response = client.get(reverse('dashboard:grm:issue_detail', kwargs={'issue': issue.auto_increment_id}))

    assert response.status_code == 200
    assert response.context['permission_to_edit'] is True
    assert response.context['enable_add_comment'] is True
    html = response.content.decode()
    # Formulaire de commentaire avec ses options de notification, et cloche de la barre du haut.
    for element_id in ('id_send_email', 'id_notify_emails', 'id_notify_users', 'notifications-bell'):
        assert f'id="{element_id}"' in html, element_id
    assert 'js/notifications_bell.js' in html

    # Bouton d'ajout de preuves (fragment chargé en AJAX par la page) : actif pour l'assigné.
    fragment = client.get(
        reverse('dashboard:grm:issue_attachments', kwargs={'issue': issue.auto_increment_id}),
        {'column': '1', 'attr': 'attachments'}, **AJAX,
    ).content.decode()
    button_end = fragment.index('id="add_attachment"')
    button = fragment[fragment.rindex('<a', 0, button_end):button_end]
    assert 'disabled' not in button
    assert IssueReadState.objects.filter(user=people['assignee'], issue=issue).exists()
    notification.refresh_from_db()
    assert notification.read_at is not None


def test_other_account_still_cannot_open_unpublished_issue(client, people, references):
    issue = _issue(references, 102, assignee=people['assignee'], publish=False)
    client.force_login(people['other'])

    response = client.get(reverse('dashboard:grm:issue_detail', kwargs={'issue': issue.auto_increment_id}))

    assert response.status_code == 403


def test_review_list_shows_unpublished_issues_assigned_to_the_user(people, references):
    mine = _issue(references, 103, assignee=people['assignee'], publish=False)
    not_mine = _issue(references, 104, assignee=people['other'], publish=False)
    request = RequestFactory().get('/grm/issue-list/datatable')
    request.user = people['assignee']

    queryset, _ = build_issue_queryset(request)

    ids = set(queryset.values_list('id', flat=True))
    assert mine.id in ids
    assert not_mine.id not in ids


def test_web_comment_keeps_notification_options_and_notifies(client, people, references):
    issue = _issue(references, 105, assignee=people['assignee'], publish=True)
    client.force_login(people['assignee'])

    response = client.post(
        reverse('dashboard:grm:add_comment_to_issue', kwargs={'issue': issue.auto_increment_id}),
        {
            'comment': 'Visite prévue demain', 'send_email': 'on',
            'notify_emails': 'Partenaire@Example.org; pas-une-adresse', 'notify_users': [str(people['chosen'].id)],
        },
        **AJAX,
    )

    assert response.status_code == 200
    comment = Comment.objects.get(issue=issue, comment='Visite prévue demain')
    assert comment.is_user_comment is True
    assert comment.send_email is True
    assert comment.notify_emails == ['partenaire@example.org']
    assert comment.notify_user_ids == [people['chosen'].id]
    assert IssueNotification.objects.filter(comment=comment, recipient=people['chosen']).exists()
    assert not IssueNotification.objects.filter(comment=comment, recipient=people['assignee']).exists()
    emails = [m for m in mail.outbox if issue.internal_code in m.subject]
    assert len(emails) == 1
    assert 'partenaire@example.org' in emails[0].bcc


def test_evidence_upload_is_reserved_to_assignee_and_admins(client, people, references):
    issue = _issue(references, 106, assignee=people['assignee'], publish=True)
    url = reverse('dashboard:grm:upload_issue_attachment', kwargs={'issue': issue.auto_increment_id})

    client.force_login(people['other'])
    assert client.get(url, **AJAX).status_code == 403
    client.force_login(people['assignee'])
    assert client.get(url, **AJAX).status_code == 200
    client.force_login(people['admin'])
    assert client.get(url, **AJAX).status_code == 200


def test_bell_counts_unread_commented_unpublished_and_statuses(client, people, references):
    admin = people['admin']
    NotificationBaseline.objects.create(user=admin, since=timezone.now() - timedelta(days=1))
    new_unpublished = _issue(references, 107, publish=False, status='registered')
    already_read = _issue(references, 108, publish=True, status='in_progress')
    IssueReadState.objects.create(user=admin, issue=already_read, last_read_at=timezone.now())
    _unread_comment_for(admin, already_read, people['other'])
    client.force_login(admin)

    response = client.get(reverse('dashboard:grm:notifications_bell'))

    assert response.status_code == 200
    data = response.json()
    assert data['count'] == 3  # 1 non lue + 1 avec nouveau commentaire + 1 non publiée
    assert new_unpublished.internal_code in data['html']
    assert already_read.internal_code in data['html']
    summary = notifications_summary(client, admin)
    assert (summary['unread_count'], summary['commented_count'], summary['unpublished_count']) == (1, 1, 1)
    assert (summary['not_started_count'], summary['in_progress_count'], summary['unresolved_count']) == (1, 1, 0)


def notifications_summary(client, user):
    from django.core.cache import cache
    from dashboard.grm.functions import get_notifications_bell_summary
    cache.clear()
    request = RequestFactory().get('/grm/notifications-bell')
    request.user = user
    return get_notifications_bell_summary(request)
