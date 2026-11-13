"""Délais de traitement par niveau (issue/deadlines.py), chaîne de remontée
Village -> Canton -> Commune -> National (authentication/models.py) et écrans associés."""
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from authentication import models as auth_models
from dashboard.diagnostics.views import compute_deadline_stats
from dashboard.grm.test_legacy_doc_sync import fake_administrative_level  # noqa: F401
from dashboard.grm.test_resolution_dates import _make_issue, auth_client, statuses  # noqa: F401
from issue.deadlines import add_delay, compute_deadline_infos, overdue_by_village
from issue.models import EscalationLevel, IssueStatus, ProcessingDelay

pytestmark = pytest.mark.django_db

MONDAY = date(2026, 11, 2)


def aware(d):
    return timezone.make_aware(datetime.combine(d, datetime.min.time()))


# --- Calcul des échéances --------------------------------------------------------------------

def test_add_delay_working_days_skips_weekends():
    assert add_delay(MONDAY, 5, working_days=True) == date(2026, 11, 9)  # lundi suivant
    assert add_delay(date(2026, 11, 6), 1, working_days=True) == date(2026, 11, 9)  # vendredi -> lundi
    assert add_delay(MONDAY, 10, working_days=True) == date(2026, 11, 16)


def test_add_delay_calendar_days():
    assert add_delay(MONDAY, 45, working_days=False) == MONDAY + timedelta(days=45)


def test_default_delays_are_seeded():
    delays = {d.level: (d.delay_days, d.working_days) for d in ProcessingDelay.objects.all()}
    assert delays['Village'] == (10, True)
    assert delays['Canton'] == (20, True)
    assert delays['Commune'] == (20, True)
    assert delays['Country'] == (45, False)
    assert delays['Prefecture'][0] is None and delays['Region'][0] is None


def test_village_delay_starts_at_received_date(auth_client, statuses):
    issue = _make_issue(auth_client.user, statuses['initial'], received_date=aware(MONDAY))
    issue.intake_date = aware(MONDAY + timedelta(days=30))  # saisie bien plus tard : ignorée
    issue.save()

    deadline = date(2026, 11, 16)  # 10 jours ouvrables
    info = compute_deadline_infos([issue], today=deadline)[issue.pk]
    assert info.level == 'Village' and info.start == MONDAY and info.deadline == deadline
    assert not info.overdue  # le jour de l'échéance n'est pas un retard

    info = compute_deadline_infos([issue], today=deadline + timedelta(days=3))[issue.pk]
    assert info.overdue and info.days_late == 3


def test_escalated_delay_starts_at_real_escalation_date(auth_client, statuses):
    issue = _make_issue(auth_client.user, statuses['initial'], received_date=aware(MONDAY))
    EscalationLevel.objects.create(issue=issue, administrative_level='Canton', due_at=timezone.now(),
                                   escalation_date=aware(date(2026, 11, 20)))  # vendredi
    info = compute_deadline_infos([issue], today=date(2026, 12, 1))[issue.pk]
    assert info.level == 'Canton'
    assert info.start == date(2026, 11, 20)
    assert info.deadline == add_delay(date(2026, 11, 20), 20)
    assert not info.overdue


def test_highest_level_wins_and_legacy_level_without_delay_is_not_late(auth_client, statuses):
    issue = _make_issue(auth_client.user, statuses['initial'], received_date=aware(MONDAY))
    same_date = timezone.now()
    EscalationLevel.objects.create(issue=issue, administrative_level='Region', due_at=same_date)
    EscalationLevel.objects.create(issue=issue, administrative_level='Canton', due_at=same_date)
    info = compute_deadline_infos([issue], today=date(2030, 1, 1))[issue.pk]
    assert info.level == 'Region'
    assert info.deadline is None and not info.overdue  # pas de délai défini pour la Région


def test_resolved_in_time_and_late(auth_client, statuses):
    on_time = _make_issue(auth_client.user, statuses['final'], received_date=aware(MONDAY),
                          resolution_real_issue_date=aware(date(2026, 11, 10)))
    late = _make_issue(auth_client.user, statuses['final'], received_date=aware(MONDAY),
                       resolution_real_issue_date=aware(date(2026, 11, 30)))
    unknown = _make_issue(auth_client.user, statuses['final'], received_date=aware(MONDAY))
    infos = compute_deadline_infos([on_time, late, unknown], today=date(2026, 12, 15))
    assert infos[on_time.pk].resolved_in_time is True
    assert infos[late.pk].resolved_in_time is False
    assert infos[unknown.pk].resolved_in_time is None
    assert not any(info.overdue for info in infos.values())  # résolues : jamais en retard

    stats = compute_deadline_stats([on_time, late, unknown], infos=infos)
    village = next(row for row in stats['levels'] if row['level'] == 'Village')
    assert (village['resolved'], village['resolved_in_time'], village['resolved_late'], village['resolved_unknown']) == (3, 1, 1, 1)
    assert village['in_time_percentage'] == 50
    assert [row['level'] for row in stats['levels']] == ['Village', 'Canton', 'Commune', 'Country']


def test_rejected_issue_is_never_late(auth_client, statuses):
    rejected = IssueStatus.objects.create(name='Rejetée', rejected_status=True)
    issue = _make_issue(auth_client.user, rejected, received_date=aware(MONDAY))
    assert not compute_deadline_infos([issue], today=date(2030, 1, 1))[issue.pk].overdue


def test_overdue_by_village_groups_counts():
    infos = {1: SimpleNamespace(overdue=True), 2: SimpleNamespace(overdue=True), 3: SimpleNamespace(overdue=False)}
    issues = [
        SimpleNamespace(pk=1, administrative_region_id=10, administrative_region_name='A'),
        SimpleNamespace(pk=2, administrative_region_id=10, administrative_region_name='A'),
        SimpleNamespace(pk=3, administrative_region_id=11, administrative_region_name='B'),
    ]
    assert overdue_by_village(issues, infos) == [{'village_id': 10, 'village_name': 'A', 'count': 2}]


# --- Chaîne de remontée Village -> Canton -> Commune -> National ------------------------------

HIERARCHY = {  # id: (type, parent_id)
    1: ('Country', None), 2: ('Region', 1), 3: ('Prefecture', 2), 4: ('Commune', 3), 5: ('Canton', 4), 6: ('Village', 5),
}


@pytest.fixture
def fake_mis(monkeypatch):
    def level(pk):
        return SimpleNamespace(id=pk, type=HIERARCHY[pk][0], name=f'L{pk}') if pk in HIERARCHY else None

    def parent(pk):
        parent_id = HIERARCHY.get(int(pk), (None, None))[1]
        if not parent_id:
            return None
        return {'administrative_id': str(parent_id), 'name': f'L{parent_id}', 'administrative_level': HIERARCHY[parent_id][0]}

    monkeypatch.setattr(auth_models.mis_objects_call, 'filter_objects',
                        lambda model, id=None, **kw: SimpleNamespace(first=lambda: level(int(id))))
    monkeypatch.setattr(auth_models, 'get_parent_administrative_level_using_mis', parent)


@pytest.mark.parametrize('current, expected', [
    (6, 'Canton'),   # Village -> Canton
    (5, 'Commune'),  # Canton -> Commune
    (4, 'Country'),  # Commune -> National (Préfecture/Région sautées)
    (3, 'Country'),  # Préfecture (ancien niveau) -> National
    (2, 'Country'),  # Région (ancien niveau) -> National
])
def test_escalation_chain(fake_mis, current, expected):
    assert auth_models.get_adl_to_escalate(current)['administrative_level'] == expected


def test_no_escalation_above_national(fake_mis):
    assert auth_models.get_adl_to_escalate(1) is None


def test_next_escalation_uses_highest_level(fake_mis, auth_client, statuses):
    issue = _make_issue(auth_client.user, statuses['initial'])
    now = timezone.now()
    EscalationLevel.objects.create(issue=issue, administrative_level='Commune', administrative_id=4, due_at=now)
    EscalationLevel.objects.create(issue=issue, administrative_level='Canton', administrative_id=5, due_at=now)
    assert auth_models.get_next_escalation_level(issue)['administrative_level'] == 'Country'

    legacy = _make_issue(auth_client.user, statuses['initial'])
    EscalationLevel.objects.create(issue=legacy, administrative_level='Region', due_at=now)  # sans id
    assert auth_models.get_next_escalation_level(legacy)['administrative_level'] == 'Country'


# --- Écrans web -------------------------------------------------------------------------------

def test_processing_delays_page_is_superuser_only(client, django_user_model):
    from django.contrib.auth.models import Group

    admin = django_user_model.objects.create_user(username='adm', email='adm@example.com', password='x')
    admin.groups.add(Group.objects.get_or_create(name='Admin')[0])
    client.force_login(admin)
    assert client.get(reverse('dashboard:diagnostics:processing_delays')).status_code == 403

    root = django_user_model.objects.create_superuser(username='root', email='root@example.com', password='x')
    client.force_login(root)
    url = reverse('dashboard:diagnostics:processing_delays')
    response = client.get(url)
    assert response.status_code == 200

    formset = response.context['formset']
    data = {'form-TOTAL_FORMS': str(len(formset.forms)), 'form-INITIAL_FORMS': str(len(formset.forms))}
    for i, form in enumerate(formset.forms):
        delay = form.instance
        data[f'form-{i}-id'] = str(delay.pk)
        data[f'form-{i}-committee_name'] = delay.committee_name
        data[f'form-{i}-delay_days'] = '15' if delay.level == 'Region' else (delay.delay_days or '')
        if delay.working_days:
            data[f'form-{i}-working_days'] = 'on'
    assert client.post(url, data).status_code == 302
    assert ProcessingDelay.objects.get(level='Region').delay_days == 15


def test_bell_and_overdue_page_list_late_issues(client, auth_client, statuses, monkeypatch):
    issue = _make_issue(auth_client.user, statuses['initial'], received_date=aware(date(2026, 1, 5)))
    Issue = type(issue)
    Issue.objects.filter(pk=issue.pk).update(administrative_region_name='Village Test')
    monkeypatch.setattr('dashboard.grm.functions.build_issue_queryset',
                        lambda request: (Issue.objects.filter(pk=issue.pk), []))
    cache.clear()
    client.force_login(auth_client.user)

    bell = client.get(reverse('dashboard:grm:notifications_bell')).json()
    assert 'Village Test' in bell['html']

    page = client.get(reverse('dashboard:grm:overdue_issues'), {'village': str(issue.administrative_region_id)})
    assert page.status_code == 200
    assert [i.pk for i, _info in page.context['late']] == [issue.pk]


def test_escalation_form_requires_real_date_not_in_future():
    from dashboard.grm.forms import IssueIssueEscalateForm

    form = IssueIssueEscalateForm(data={'escalate_reason': 'x'}, initial={})
    form.is_valid()
    assert 'escalation_date' in form.errors
    future = (timezone.localdate() + timedelta(days=1)).isoformat()
    form = IssueIssueEscalateForm(data={'escalate_reason': 'x', 'escalation_date': future}, initial={})
    form.is_valid()
    assert 'escalation_date' in form.errors


def test_received_date_required_on_details_form(auth_client):
    from dashboard.grm.forms import NewIssueDetailsForm

    form = NewIssueDetailsForm(data={}, initial={'doc': {}, 'user': auth_client.user})
    form.is_valid()
    assert 'received_date' in form.errors
    assert form.fields['received_date'].initial == timezone.localdate().isoformat()


# --- Pages web réelles : dates préremplies avec aujourd'hui --------------------------------

@pytest.fixture
def draft_issue(auth_client, statuses):
    """Brouillon d'enregistrement web (assistant en plusieurs étapes) du compte connecté."""
    issue = _make_issue(auth_client.user, statuses['initial'], contact_medium='anonymous')
    type(issue).objects.filter(pk=issue.pk).update(confirmed=False)
    return issue


def test_web_step_pages_show_new_fields(client, auth_client, draft_issue):
    client.force_login(auth_client.user)
    today = timezone.localdate().isoformat()

    step2 = client.get(reverse('dashboard:grm:new_issue_step_2', kwargs={'issue': draft_issue.auto_increment_id}))
    assert step2.status_code == 200
    assert 'name="refugee_or_idp"' in step2.content.decode()

    step3 = client.get(reverse('dashboard:grm:new_issue_step_3', kwargs={'issue': draft_issue.auto_increment_id}))
    assert step3.status_code == 200
    html = step3.content.decode()
    assert 'name="received_date"' in html and f'value="{today}"' in html


def test_web_escalation_modal_prefills_today(client, auth_client, statuses):
    issue = _make_issue(auth_client.user, statuses['initial'], assignee=auth_client.user)
    client.force_login(auth_client.user)
    response = client.get(
        reverse('dashboard:grm:submit_issue_escalate', kwargs={'issue': issue.auto_increment_id}),
        HTTP_X_REQUESTED_WITH='XMLHttpRequest',
    )
    assert response.status_code == 200
    html = response.content.decode()
    assert 'name="escalation_date"' in html
    assert f'value="{timezone.localdate().isoformat()}"' in html
