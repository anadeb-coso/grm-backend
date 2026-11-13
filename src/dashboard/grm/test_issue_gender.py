"""Le sexe du plaignant (`Issue.gender`) est enregistré depuis le web et depuis le mobile."""
import pytest

from dashboard.grm.serializers import LegacyIssueDoc
from dashboard.grm.test_legacy_doc_sync import fake_administrative_level  # noqa: F401
from dashboard.grm.test_resolution_dates import _make_issue, auth_client, statuses  # noqa: F401

pytestmark = pytest.mark.django_db


def test_web_save_persists_gender(auth_client, statuses):
    issue = _make_issue(auth_client.user, statuses['initial'])
    doc = LegacyIssueDoc(issue)
    doc['gender'] = 'Female'
    doc.save()

    issue.refresh_from_db()
    assert issue.gender == 'Female'
    assert LegacyIssueDoc(issue)['gender'] == 'Female'  # pré-remplissage du formulaire


def test_mobile_push_saves_gender(auth_client, statuses):
    issue = _make_issue(auth_client.user, statuses['initial'])
    payload = {'changes': {'issues': {'created': [], 'deleted': [], 'updated': [{
        'id': str(issue.pk), 'gender': 'male', '_changed': 'gender',
    }]}}}
    resp = auth_client.post('/api/sync/push/', payload, format='json')
    assert resp.status_code == 204, getattr(resp, 'data', None)

    issue.refresh_from_db()
    assert issue.gender == 'male'


@pytest.mark.parametrize('answer, expected', [('yes', True), ('no', False), ('', None)])
def test_web_step_2_saves_refugee_or_idp(auth_client, statuses, answer, expected):
    """Étape 2 web (NewIssuePersonFormView.set_person_fields) : 'yes'/'no'/vide → True/False/None."""
    from dashboard.grm.views import NewIssueMixin

    issue = _make_issue(auth_client.user, statuses['initial'])
    view = NewIssueMixin()
    view.doc = LegacyIssueDoc(issue)
    view.set_person_fields({
        'citizen': '', 'citizen_type': '', 'citizen_age_group': '', 'citizen_or_group': '',
        'gender': '', 'refugee_or_idp': answer,
    })
    view.doc.save()

    issue.refresh_from_db()
    assert issue.refugee_or_idp is expected


def test_web_form_prefills_refugee_or_idp():
    from dashboard.grm.forms import NewIssuePersonForm

    form = NewIssuePersonForm(initial={'doc': {'refugee_or_idp': True}})
    assert form.fields['refugee_or_idp'].initial == 'yes'
    form = NewIssuePersonForm(initial={'doc': {'refugee_or_idp': None}})
    assert form.fields['refugee_or_idp'].initial is None


def test_mobile_push_saves_refugee_or_idp(auth_client, statuses):
    issue = _make_issue(auth_client.user, statuses['initial'])
    payload = {'changes': {'issues': {'created': [], 'deleted': [], 'updated': [{
        'id': str(issue.pk), 'refugee_or_idp': True, '_changed': 'refugee_or_idp',
    }]}}}
    resp = auth_client.post('/api/sync/push/', payload, format='json')
    assert resp.status_code == 204, getattr(resp, 'data', None)

    issue.refresh_from_db()
    assert issue.refugee_or_idp is True
