"""Notifications des commentaires écrits (issue/notifications.py) : destinataires, email, anti-
doublon, et table `issue_notifications` du protocole de sync mobile (pull filtré sur le
destinataire, push limité au marquage « lu »)."""
import json
import uuid

import pytest
from django.contrib.auth.models import Group
from django.core import mail
from django.db.models import query as query_module
from django.utils import timezone
from rest_framework.test import APIClient

from administrativelevels.models import AdministrativeLevel
from issue import notifications
from issue.models import (
    Adl, Comment, Issue, IssueCategory, IssueNotification, IssueStatus, IssueType, NotificationRecipient,
)

pytestmark = pytest.mark.django_db

FAKE_REGION_ID = 999011


@pytest.fixture(autouse=True)
def fake_administrative_levels(monkeypatch):
    """`mis` n'est jamais interrogée (cf. sync/tests/test_sync.py) : le village de l'issue n'a pas
    de niveau parent dans ces tests."""
    real_get = query_module.QuerySet.get

    def _fake_get(self, *args, **kwargs):
        if self.model is AdministrativeLevel:
            pk = kwargs.get('pk', kwargs.get('id'))
            if pk is not None and int(pk) == FAKE_REGION_ID:
                return AdministrativeLevel(id=FAKE_REGION_ID, name='Village Test', type='Village')
            raise AdministrativeLevel.DoesNotExist()
        return real_get(self, *args, **kwargs)

    monkeypatch.setattr(query_module.QuerySet, 'get', _fake_get)


@pytest.fixture(autouse=True)
def no_other_sync_tasks(monkeypatch):
    """Les tâches existantes lancées à chaque sync (SMS, escalades, email « nouvelle issue »...)
    sont hors sujet ici : neutralisées pour ne compter que les emails de commentaire."""
    from sync import views
    for name in ('check_issues', 'escalate_issues', 'send_sms_message', 'send_a_new_issue_notification',
                 'send_issue_status_notifications'):
        monkeypatch.setattr(views, name, lambda: None)


def _user(django_user_model, name, **kwargs):
    return django_user_model.objects.create_user(
        username=name, email=f'{name}@example.com', password='pass1234', first_name=name.title(), **kwargs,
    )


def _api_client(user):
    client = APIClient()
    resp = client.post('/api/auth/token/', {'username': user.username, 'password': 'pass1234'})
    assert resp.status_code == 200, resp.data
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
    return client


@pytest.fixture
def people(django_user_model):
    return {name: _user(django_user_model, name) for name in ('author', 'assignee', 'reporter', 'chosen', 'stranger')}


@pytest.fixture
def issue(people):
    now = timezone.now()
    return Issue.objects.create(
        internal_code=f'DRP-NOTIF-{uuid.uuid4().hex[:8]}', tracking_code='Tree12', auto_increment_id=7,
        description='Pont effondré au village', confirmed=True, source='mobile',
        created_date=now, intake_date=now, issue_date=now,
        status=IssueStatus.objects.create(name='Enregistrée', initial_status=True),
        category=IssueCategory.objects.create(name='Infrastructures'),
        issue_type=IssueType.objects.create(name='Plainte'),
        administrative_region=AdministrativeLevel(id=FAKE_REGION_ID, name='Village Test', type='Village'),
        administrative_region_name='Village Test',
        assignee=people['assignee'], assignee_name='Assignee',
        reporter=people['reporter'], reporter_name='Reporter',
    )


def _comment_record(issue, author, **overrides):
    record = {
        'id': str(uuid.uuid4()),
        'issue': str(issue.id),
        'author': author.id,
        'author_name': author.name,
        'comment': 'Les travaux commencent lundi.',
        'due_at': timezone.now().isoformat(),
        'is_deleted': False,
        'is_user_comment': True,
        'send_email': True,
        'notify_emails': '[]',
        'notify_user_ids': '[]',
    }
    record.update(overrides)
    return record


def _comment_emails(issue):
    """Emails de commentaire de `issue` (la création des comptes de test envoie aussi des emails)."""
    return [m for m in mail.outbox if issue.internal_code in m.subject]


def _push(client, table_changes):
    return client.post('/api/sync/push/', {'changes': table_changes, 'last_pulled_at': 0}, format='json')


def test_written_comment_from_mobile_notifies_members_chosen_accounts_and_emails(people, issue):
    # Listes de l'équipe MGP (admin Django) : seules les adresses actives sont destinataires.
    NotificationRecipient.objects.create(email='safeguard@example.org', group=NotificationRecipient.GROUP_SAFEGUARD_SPECIALISTS)
    NotificationRecipient.objects.create(email='former@example.org', group=NotificationRecipient.GROUP_OTHERS, is_active=False)
    client = _api_client(people['author'])
    record = _comment_record(
        issue, people['author'],
        # Le mobile stocke ces listes en chaîne JSON (colonne `string` WatermelonDB).
        notify_emails=json.dumps(['Extra@Example.org', 'pas-une-adresse']),
        notify_user_ids=json.dumps([people['chosen'].id]),
    )

    resp = _push(client, {'comments': {'created': [record], 'updated': [], 'deleted': []}})

    assert resp.status_code == 204, resp.data
    comment = Comment.objects.get(pk=record['id'])
    assert comment.notify_emails == ['Extra@Example.org', 'pas-une-adresse']
    assert comment.notifications_processed_at is not None

    recipients = set(IssueNotification.objects.filter(comment=comment).values_list('recipient__username', flat=True))
    assert recipients == {'assignee', 'reporter', 'chosen'}  # ni l'auteur, ni un compte sans lien

    notification = IssueNotification.objects.get(comment=comment, recipient=people['assignee'])
    assert notification.issue_code == issue.internal_code
    assert notification.comment_text == 'Les travaux commencent lundi.'
    assert notification.read_at is None

    assert len(_comment_emails(issue)) == 1
    message = _comment_emails(issue)[0]
    assert issue.internal_code in message.subject
    assert {'assignee@example.com', 'reporter@example.com', 'chosen@example.com', 'extra@example.org'} <= set(message.bcc)
    assert 'safeguard@example.org' in message.bcc
    assert 'former@example.org' not in message.bcc
    assert 'author@example.com' not in message.bcc
    assert 'pas-une-adresse' not in message.bcc
    html = message.alternatives[0][0]
    for expected in ('Infrastructures', 'Pont effondré au village', 'Les travaux commencent lundi.', 'Village Test'):
        assert expected in html


def test_comment_without_email_option_only_creates_in_app_notifications(people, issue):
    client = _api_client(people['author'])
    record = _comment_record(issue, people['author'], send_email=False)

    assert _push(client, {'comments': {'created': [record], 'updated': [], 'deleted': []}}).status_code == 204

    assert IssueNotification.objects.filter(comment_id=record['id']).count() == 2  # assigné + déclarant
    assert _comment_emails(issue) == []


def test_automatic_action_comment_is_not_notified(people, issue):
    """Commentaire ajouté par une action (acceptée, résolue...) : `is_user_comment` absent, comme
    pour les versions du mobile antérieures à cette fonctionnalité."""
    client = _api_client(people['author'])
    record = _comment_record(issue, people['author'])
    for field in ('is_user_comment', 'send_email', 'notify_emails', 'notify_user_ids'):
        record.pop(field)

    assert _push(client, {'comments': {'created': [record], 'updated': [], 'deleted': []}}).status_code == 204

    assert not IssueNotification.objects.exists()
    assert _comment_emails(issue) == []


def test_comment_is_notified_only_once(people, issue):
    comment = Comment.objects.create(
        issue=issue, author=people['author'], author_name='Author', comment='Relance',
        due_at=timezone.now(), is_user_comment=True, send_email=True,
    )

    notifications.send_comment_notifications()
    notifications.send_comment_notifications()

    assert IssueNotification.objects.filter(comment=comment).count() == 2
    assert len(_comment_emails(issue)) == 1


def test_only_accounts_working_specifically_in_the_village_are_notified(django_user_model, people, issue):
    """Membres notifiés d'office : participants et comptes dont le périmètre contient le village
    lui-même. Ni les comptes de portée nationale (TOGO, "1"), ni les administrateurs, ni les agents
    qui ne couvrent le village que par un niveau supérieur (canton...)."""
    from authentication.models import GovernmentWorker

    village_facilitator = _user(django_user_model, 'facilitator')
    other_facilitator = _user(django_user_model, 'elsewhere')
    national_facilitator = _user(django_user_model, 'nationalfc')
    village_agent = _user(django_user_model, 'villageagent')
    canton_agent = _user(django_user_model, 'cantonagent')
    national_agent = _user(django_user_model, 'nationalagent')
    admin = _user(django_user_model, 'admin')
    admin.groups.add(Group.objects.get_or_create(name='Admin')[0])
    viewer = _user(django_user_model, 'viewer')
    viewer.groups.add(Group.objects.get_or_create(name='ViewerOfAllIssues')[0])
    Adl.objects.create(name='EADL village', representative=village_facilitator, administrative_region_ids=[str(FAKE_REGION_ID)])
    Adl.objects.create(name='EADL ailleurs', representative=other_facilitator, administrative_region_ids=['123456'])
    Adl.objects.create(name='EADL national', representative=national_facilitator, administrative_region_ids=['1'])
    GovernmentWorker.objects.create(user=village_agent, department=1, administrative_ids=[str(FAKE_REGION_ID)])
    GovernmentWorker.objects.create(user=canton_agent, department=1, administrative_id='777')  # canton du village
    GovernmentWorker.objects.create(user=national_agent, department=1, administrative_id='1')
    comment = Comment.objects.create(
        issue=issue, author=people['author'], author_name='Author', comment='Point de situation',
        due_at=timezone.now(), is_user_comment=True,
    )

    notifications.send_comment_notifications([comment.pk])

    recipients = set(IssueNotification.objects.filter(comment=comment).values_list('recipient__username', flat=True))
    assert recipients == {'assignee', 'reporter', 'facilitator', 'villageagent'}


def test_pull_returns_only_the_users_own_notifications(people, issue):
    comment = Comment.objects.create(
        issue=issue, author=people['author'], author_name='Author', comment='Avis',
        due_at=timezone.now(), is_user_comment=True,
    )
    notifications.send_comment_notifications([comment.pk])

    resp = _api_client(people['assignee']).get('/api/sync/pull/', {'last_pulled_at': 0})

    assert resp.status_code == 200
    pulled = resp.data['changes']['issue_notifications']['updated']
    assert [n['recipient'] for n in pulled] == [people['assignee'].id]
    assert pulled[0]['comment_text'] == 'Avis'


def test_push_marks_own_notification_read_and_rejects_others(people, issue):
    comment = Comment.objects.create(
        issue=issue, author=people['author'], author_name='Author', comment='Avis',
        due_at=timezone.now(), is_user_comment=True,
    )
    notifications.send_comment_notifications([comment.pk])
    mine = IssueNotification.objects.get(comment=comment, recipient=people['assignee'])
    other = IssueNotification.objects.get(comment=comment, recipient=people['reporter'])
    read_at = timezone.now().isoformat()

    resp = _push(_api_client(people['assignee']), {'issue_notifications': {
        'created': [],
        'updated': [{'id': str(mine.id), 'read_at': read_at}, {'id': str(other.id), 'read_at': read_at}],
        'deleted': [],
    }})

    assert resp.status_code == 200
    assert resp.data['rejected'] == {'issue_notifications': [str(other.id)]}
    mine.refresh_from_db()
    other.refresh_from_db()
    assert mine.read_at is not None
    assert other.read_at is None


def test_notification_accounts_endpoint_lists_active_accounts(django_user_model, people):
    _user(django_user_model, 'inactive', is_active=False)

    resp = _api_client(people['author']).get('/api/notification-accounts/')

    assert resp.status_code == 200
    names = {account['name'] for account in resp.data}
    assert 'Chosen' in {name.strip() for name in names}
    assert all(set(account) == {'id', 'name'} for account in resp.data)
    assert 'inactive' not in {account['name'].strip().lower() for account in resp.data}


# ---------------------------------------------------------------------------
# Acteurs de terrain du village (membres CVD, FC/AC, FT, SZ) en copie de toutes les notifications
# ---------------------------------------------------------------------------

def _village_actor(django_user_model, name, group, villages, **kwargs):
    user = _user(django_user_model, name, **kwargs)
    user.groups.add(Group.objects.get_or_create(name=group)[0])
    Adl.objects.create(name=f'EADL {name}', representative=user, smallest_administrative_level_ids=villages)
    return user


@pytest.fixture
def village_actors(django_user_model):
    village = [str(FAKE_REGION_ID)]
    return {
        'cvd': _village_actor(django_user_model, 'cvdmember', 'CVGPMembers', village),
        'fc': _village_actor(django_user_model, 'facilitator', 'CommunityFacilitator', village),
        'ft': _village_actor(django_user_model, 'technician', 'TechnicalFacilitator', village),
        'sz': _village_actor(django_user_model, 'supervisor', 'Supervisor', village),
        # Hors règle : autre village, portée nationale seulement, compte inactif, groupe non concerné.
        'elsewhere': _village_actor(django_user_model, 'fcelsewhere', 'CommunityFacilitator', ['123456']),
        'national': _village_actor(django_user_model, 'nationalsz', 'Supervisor', ['1']),
        'inactive': _village_actor(django_user_model, 'oldfc', 'CommunityFacilitator', village, is_active=False),
        'other_group': _village_actor(django_user_model, 'accountant', 'Accountant', village),
    }


def _team_recipients():
    R = NotificationRecipient
    R.objects.create(email='safeguard@example.org', group=R.GROUP_SAFEGUARD_SPECIALISTS)
    R.objects.create(email='coordinator@example.org', group=R.GROUP_COORDINATORS)
    R.objects.create(email='regional@example.org', group=R.GROUP_REGIONAL_COORDINATORS)
    R.objects.create(email='former@example.org', group=R.GROUP_COORDINATORS, is_active=False)


ACTOR_EMAILS = {'cvdmember@example.com', 'facilitator@example.com', 'technician@example.com', 'supervisor@example.com'}


def test_village_actors_are_cvd_fc_ft_sz_working_directly_in_the_village(village_actors):
    assert notifications.village_actor_emails(FAKE_REGION_ID) == sorted(ACTOR_EMAILS) or \
        set(notifications.village_actor_emails(FAKE_REGION_ID)) == ACTOR_EMAILS
    assert notifications.village_actor_ids(None) == set()


@pytest.mark.parametrize('send', [
    lambda legacy: __import__('dashboard.grm.functions', fromlist=['x']).send_notification_by_mail(legacy),
    lambda legacy: __import__('dashboard.grm.functions', fromlist=['x']).send_notification_on_escalation_by_mail(legacy),
    lambda legacy: __import__('dashboard.grm.functions', fromlist=['x']).send_issue_status_update_notification_by_mail(legacy, 'opened'),
], ids=['nouvelle-issue', 'escalade', 'changement-de-statut'])
def test_action_emails_copy_the_village_actors(village_actors, issue, send):
    from dashboard.grm.serializers import issue_to_legacy_dict
    from issue.models import EscalationLevel

    # L'email d'escalade décrit le niveau vers lequel l'issue est escaladée.
    EscalationLevel.objects.create(issue=issue, administrative_level='Canton', name='Canton Test', due_at=timezone.now())
    _team_recipients()

    send(issue_to_legacy_dict(issue))

    emails = _comment_emails(issue)
    assert len(emails) == 1
    # Listes de l'équipe MGP lues dans la table : mêmes rôles qu'avant (spécialistes en destinataires).
    assert emails[0].to == ['safeguard@example.org']
    assert {'coordinator@example.org', 'regional@example.org'} <= set(emails[0].cc)
    assert 'former@example.org' not in emails[0].cc
    assert ACTOR_EMAILS <= set(emails[0].cc)
    assert not {'fcelsewhere@example.com', 'nationalsz@example.com', 'oldfc@example.com', 'accountant@example.com'} & set(emails[0].cc)


def test_assignment_email_copies_the_village_actors(village_actors, people, issue):
    from dashboard.grm.functions import send_assignee_notification_by_mail
    from dashboard.grm.serializers import issue_to_legacy_dict

    _team_recipients()

    send_assignee_notification_by_mail(issue_to_legacy_dict(issue), people['assignee'])

    emails = _comment_emails(issue)
    assert len(emails) == 1
    assert ACTOR_EMAILS <= set(emails[0].cc)
    # Comme avant : l'assignation copie les coordinateurs régionaux, pas les coordinateurs.
    assert 'regional@example.org' in emails[0].cc
    assert 'coordinator@example.org' not in emails[0].cc


def test_comment_notifies_the_village_actors(village_actors, people, issue):
    comment = Comment.objects.create(
        issue=issue, author=people['author'], author_name='Author', comment='Réunion au village',
        due_at=timezone.now(), is_user_comment=True, send_email=True,
    )

    notifications.send_comment_notifications([comment.pk])

    recipients = set(IssueNotification.objects.filter(comment=comment).values_list('recipient__email', flat=True))
    assert ACTOR_EMAILS <= recipients
    assert ACTOR_EMAILS <= set(_comment_emails(issue)[0].bcc)
