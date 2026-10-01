import datetime

import pytest
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

from internet_credits import services
from internet_credits.models import (
    InternetCreditBeneficiary, InternetCreditCampaign, InternetCreditConfirmation,
)

from .conftest import SIGNATURE, api_client, confirmation_record

pytestmark = pytest.mark.django_db


def _line(campaign, user):
    return InternetCreditBeneficiary.objects.get(campaign=campaign, cvgp_member=user, is_deleted=False)


def _pull(client, **params):
    resp = client.get('/api/sync/pull/', {'last_pulled_at': 0, **params})
    assert resp.status_code == 200, resp.data
    return resp.data['changes']


def _push_confirmations(client, records):
    return client.post(
        '/api/sync/push/',
        {'changes': {'internet_credit_confirmations': {'created': [], 'updated': records, 'deleted': []}}},
        format='json',
    )


# ---- Génération des lignes ----

def test_campaign_generates_one_line_per_cvgp_member_with_cvd(actors, campaign):
    lines = InternetCreditBeneficiary.objects.filter(campaign=campaign, is_deleted=False)
    assert lines.count() == 2  # un CVGP = un CVD, même avec deux villages
    line = _line(campaign, actors['cvgp'])
    assert campaign.period == datetime.date(2026, 9, 1)
    assert line.cvd_id == 7001 and line.cvd_name == 'KPEKPE'
    assert line.village_ids_value == ['101', '102']
    assert line.phone_number == '22890000000'
    assert line.cvgp_message == (
        "CVGP du CVD KPEKPE a bien reçu le crédit internet pour le mois de Septembre 2026, "
        "et j'en confirme sa réception"
    )


def test_regeneration_is_idempotent_and_drops_unconfirmed_former_members(actors, campaign):
    services.create_confirmation(actors['cvgp'], confirmation_record(_line(campaign, actors['cvgp'])), 'grm_mobile')
    actors['cvgp'].groups.remove(Group.objects.get(name='CVGPMembers'))
    actors['cvgp_other'].groups.remove(Group.objects.get(name='CVGPMembers'))

    stats = services.sync_campaign_beneficiaries(campaign)

    assert stats['created'] == 0
    assert stats['removed'] == 1  # cvgp_other : pas encore confirmé -> retiré
    assert _line(campaign, actors['cvgp'])  # déjà confirmé -> conservé tel quel


def test_campaign_edit_refreshes_only_unconfirmed_messages(actors, campaign):
    services.create_confirmation(actors['cvgp'], confirmation_record(_line(campaign, actors['cvgp'])), 'grm_mobile')
    campaign.cvgp_message_template = 'Reçu pour {cvd} ({mois} {annee})'
    campaign.save()
    services.refresh_campaign_messages(campaign)

    assert _line(campaign, actors['cvgp']).cvgp_message.startswith('CVGP du CVD KPEKPE')
    assert _line(campaign, actors['cvgp_other']).cvgp_message == 'Reçu pour DAPAONG (Septembre 2026)'


# ---- Pull WatermelonDB : visibilité ----

def test_pull_scopes_lines_to_cvgp_member_and_covering_fc(actors, campaign):
    line_id = str(_line(campaign, actors['cvgp']).id)
    other_id = str(_line(campaign, actors['cvgp_other']).id)

    def visible(user):
        changes = _pull(api_client(user))
        assert {r['id'] for r in changes['internet_credit_campaigns']['updated']} == {str(campaign.id)}
        return {r['id'] for r in changes['internet_credit_beneficiaries']['updated']}

    assert visible(actors['cvgp']) == {line_id}
    assert visible(actors['fc']) == {line_id}  # village 102 dans son périmètre
    assert visible(actors['fc_out']) == set()
    assert visible(actors['nobody']) == set()  # village 101, mais pas FC/AC
    assert other_id not in visible(actors['fc'])


def test_pull_never_sends_signature(actors, campaign):
    services.create_confirmation(actors['cvgp'], confirmation_record(_line(campaign, actors['cvgp'])), 'grm_mobile')
    rows = _pull(api_client(actors['fc']))['internet_credit_confirmations']['updated']
    assert len(rows) == 1
    assert 'signature' not in rows[0] and rows[0]['has_signature'] is True


def test_pull_full_tables_resends_rows_older_than_last_pulled_at(actors, campaign):
    client = api_client(actors['cvgp'])
    first = client.get('/api/sync/pull/', {'last_pulled_at': 0}).data
    later = int(first['timestamp']) + 1000

    assert _pull(client, last_pulled_at=later)['internet_credit_beneficiaries']['updated'] == []
    rows = _pull(client, last_pulled_at=later, full_tables='internet_credit_beneficiaries')
    assert len(rows['internet_credit_beneficiaries']['updated']) == 1
    assert rows['issues']['updated'] == []  # les autres tables restent incrémentales


def test_soft_deleted_campaign_is_propagated_as_tombstones(actors, campaign):
    client = api_client(actors['cvgp'])
    timestamp = client.get('/api/sync/pull/', {'last_pulled_at': 0}).data['timestamp']
    line_id = _line(campaign, actors['cvgp']).id

    services.soft_delete_campaign(campaign)

    changes = _pull(client, last_pulled_at=timestamp)
    assert str(campaign.id) in {str(i) for i in changes['internet_credit_campaigns']['deleted']}
    assert str(line_id) in {str(i) for i in changes['internet_credit_beneficiaries']['deleted']}


# ---- Push WatermelonDB ----

def test_push_cvgp_confirmation_is_created_with_server_side_author(actors, campaign):
    line = _line(campaign, actors['cvgp'])
    record = confirmation_record(line, confirmed_by=actors['fc'].id)  # valeur client ignorée
    resp = _push_confirmations(api_client(actors['cvgp']), [record])

    assert resp.status_code == 204, resp.data
    confirmation = InternetCreditConfirmation.objects.get(id=record['id'])
    assert confirmation.role == 'cvgp'
    assert confirmation.confirmed_by == actors['cvgp']
    assert confirmation.message == line.cvgp_message
    assert confirmation.signature == SIGNATURE


def test_push_retry_is_idempotent(actors, campaign):
    client = api_client(actors['cvgp'])
    record = confirmation_record(_line(campaign, actors['cvgp']))
    assert _push_confirmations(client, [record]).status_code == 204
    assert _push_confirmations(client, [record]).status_code == 204
    assert InternetCreditConfirmation.objects.filter(beneficiary__campaign=campaign).count() == 1


def test_push_out_of_scope_confirmations_are_rejected_without_failing_push(actors, campaign):
    other_line = _line(campaign, actors['cvgp_other'])
    by_cvgp = confirmation_record(other_line)  # pas sa ligne
    resp = _push_confirmations(api_client(actors['cvgp']), [by_cvgp])
    assert resp.status_code == 200
    assert resp.data['rejected'] == {'internet_credit_confirmations': [by_cvgp['id']]}

    by_fc_out = confirmation_record(_line(campaign, actors['cvgp']))
    resp = _push_confirmations(api_client(actors['fc_out']), [by_fc_out])
    assert resp.data['rejected']['internet_credit_confirmations'] == [by_fc_out['id']]
    assert not InternetCreditConfirmation.objects.exists()


def test_push_confirmation_on_deleted_campaign_is_rejected(actors, campaign):
    record = confirmation_record(_line(campaign, actors['cvgp']))
    services.soft_delete_campaign(campaign)
    resp = _push_confirmations(api_client(actors['cvgp']), [record])
    assert resp.data['rejected']['internet_credit_confirmations'] == [record['id']]


# ---- Règles de notification + API DCC ----

def _notification_ids(user):
    resp = api_client(user).get('/api/internet-credits/notifications/')
    assert resp.status_code == 200
    return {n['id']: n for n in resp.data['results']}


def test_notification_rules_for_cvgp_and_fc(actors, campaign):
    line = _line(campaign, actors['cvgp'])
    line_id = str(line.id)

    assert set(_notification_ids(actors['cvgp'])) == {line_id}
    notification = _notification_ids(actors['fc'])[line_id]
    assert notification['role'] == 'fc' and notification['cvd_name'] == 'KPEKPE'

    # Le FC confirme seul : sa notification reste (le CVGP n'a pas encore confirmé).
    resp = api_client(actors['fc']).post('/api/internet-credits/confirmations/', {
        'beneficiary': line_id, 'checked': True, 'signature': SIGNATURE, 'description': 'Vérifié par appel',
    }, format='json')
    assert resp.status_code == 201, resp.data
    notification = _notification_ids(actors['fc'])[line_id]
    assert notification['my_confirmation'] is not None and notification['cvgp_confirmation'] is None
    assert line_id in _notification_ids(actors['cvgp'])

    # Le CVGP confirme : les deux notifications disparaissent.
    services.create_confirmation(actors['cvgp'], confirmation_record(line), 'grm_mobile')
    assert line_id not in _notification_ids(actors['cvgp'])
    assert line_id not in _notification_ids(actors['fc'])


def test_fc_notification_stays_when_only_cvgp_confirmed(actors, campaign):
    line = _line(campaign, actors['cvgp'])
    services.create_confirmation(actors['cvgp'], confirmation_record(line), 'grm_mobile')
    assert str(line.id) not in _notification_ids(actors['cvgp'])
    assert _notification_ids(actors['fc'])[str(line.id)]['cvgp_confirmation'] is not None


def test_reset_confirmation_brings_notification_back(actors, campaign):
    line = _line(campaign, actors['cvgp'])
    confirmation, _ = services.create_confirmation(actors['cvgp'], confirmation_record(line), 'grm_mobile')
    services.reset_confirmation(confirmation)
    assert str(line.id) in _notification_ids(actors['cvgp'])
    # et il peut confirmer à nouveau
    _, created = services.create_confirmation(actors['cvgp'], confirmation_record(line), 'grm_mobile')
    assert created


@pytest.mark.parametrize('payload, code', [
    ({'checked': False, 'signature': SIGNATURE}, 'not_checked'),
    ({'checked': True, 'signature': 'pas une image'}, 'invalid_signature'),
])
def test_api_rejects_invalid_confirmation(actors, campaign, payload, code):
    line = _line(campaign, actors['cvgp'])
    resp = api_client(actors['cvgp']).post(
        '/api/internet-credits/confirmations/', {'beneficiary': str(line.id), **payload}, format='json',
    )
    assert resp.status_code == 400 and resp.data['code'] == code


def test_api_requires_authentication(campaign):
    assert APIClient().get('/api/internet-credits/notifications/').status_code == 401


def test_period_is_unique_among_active_campaigns(campaign):
    services.soft_delete_campaign(campaign)
    # Un mois supprimé peut être ré-enregistré.
    InternetCreditCampaign.objects.create(period=datetime.date(2026, 9, 1), sent_date=datetime.date(2026, 9, 3))
