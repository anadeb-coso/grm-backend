import uuid

import pytest
from django.contrib.auth.models import Group
from django.db.models import query as query_module
from django.urls import reverse
from django.utils import timezone

from administrativelevels.models import AdministrativeLevel
from issue.models import IssueCategory, IssueStatus, IssueType, Issue

# `Issue.citizen_type` est stocké en chaîne ('1') : le détail web doit tout de même masquer le
# nom d'un plaignant qui a demandé la confidentialité (`doc.citizen_type == 1`, cf.
# dashboard/grm/serializers.py::_citizen_type_int) et afficher « Inscrite par ».
pytestmark = pytest.mark.django_db(databases=['default', 'mis'])

FAKE_REGION_ID = 999013


@pytest.fixture(autouse=True)
def isolate_external_calls(monkeypatch):
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


def _detail_html(client, django_user_model, citizen_type, number):
    AdministrativeLevel.objects.using('mis').get_or_create(id=FAKE_REGION_ID, defaults={'name': 'Village Test', 'type': 'Village'})
    # Superviseur : ni Admin (qui voit tout), ni assigné.
    viewer = django_user_model.objects.create_user(
        username=f'lecteur{number}', email=f'lecteur{number}@example.com', password='pass1234',
    )
    viewer.groups.add(Group.objects.get_or_create(name='Supervisor')[0])
    now = timezone.now()
    issue = Issue.objects.create(
        internal_code=f'DRP-CT-{uuid.uuid4().hex[:8]}', auto_increment_id=number, description='Forage en panne',
        confirmed=True, source='mobile', publish=True, notification_send=True,
        created_date=now, intake_date=now, issue_date=now,
        status=IssueStatus.objects.create(name='Enregistrée', initial_status=True),
        category=IssueCategory.objects.create(name='Infrastructures'),
        issue_type=IssueType.objects.create(name='Plainte'),
        administrative_region=AdministrativeLevel(id=FAKE_REGION_ID, name='Village Test', type='Village'),
        administrative_region_name='Village Test',
        citizen='Kossi Plaignant', citizen_type=citizen_type,
    )
    client.force_login(viewer)
    response = client.get(reverse('dashboard:grm:issue_detail', kwargs={'issue': issue.auto_increment_id}))
    assert response.status_code == 200
    return response.content.decode()


def test_confidential_name_is_hidden_from_a_non_assignee(client, django_user_model):
    html = _detail_html(client, django_user_model, '1', 201)

    assert 'Confidential' in html
    assert 'Complainant' in html  # « Inscrite par »
    assert '<div id="citizen">' not in html


def test_non_confidential_name_stays_viewable(client, django_user_model):
    html = _detail_html(client, django_user_model, '2', 202)

    assert 'Confidential' not in html
    assert 'Citizen on behalf of others' in html
    assert '<div id="citizen">' in html
