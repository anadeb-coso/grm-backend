"""Rattachement membre CVGP -> CVD contre une VRAIE base `mis` de test (tables
`administrativelevels_*` créées par src/conftest.py), sans le mock `fake_mis` utilisé ailleurs."""
import datetime

import pytest

from administrativelevels.models import CVD, AdministrativeLevel, GeographicalUnit
from internet_credits import services
from internet_credits.models import InternetCreditBeneficiary, InternetCreditCampaign
from internet_credits.services import fetch_cvd_info as real_fetch_cvd_info  # avant le monkeypatch

from .conftest import make_user

pytestmark = pytest.mark.django_db(databases=['default', 'mis'])


@pytest.fixture
def mis_cvds():
    canton = AdministrativeLevel.objects.create(name='NANO', type='Canton')
    unit = GeographicalUnit.objects.create(canton=canton, attributed_number_in_canton=1, unique_code='UG-TEST-1')
    named = CVD.objects.create(name='KPEKPE', geographical_unit=unit, unique_code='CVD-TEST-1')
    unnamed = CVD.objects.create(name='', geographical_unit=unit, unique_code='CVD-TEST-2')
    villages = {
        'kpekpe_centre': AdministrativeLevel.objects.create(name='KPEKPE CENTRE', type='Village', parent=canton, cvd=named),
        'kpekpe_nord': AdministrativeLevel.objects.create(name='KPEKPE NORD', type='Village', parent=canton, cvd=named),
        'bola': AdministrativeLevel.objects.create(name='BOLA', type='Village', parent=canton, cvd=unnamed),
        'pilougou': AdministrativeLevel.objects.create(name='PILOUGOU', type='Village', parent=canton, cvd=unnamed),
        'orphan': AdministrativeLevel.objects.create(name='SANS CVD', type='Village', parent=canton),
    }
    return {'named': named, 'unnamed': unnamed, 'villages': villages}


@pytest.fixture(autouse=True)
def use_real_mis(monkeypatch):
    monkeypatch.setattr(services, 'fetch_cvd_info', real_fetch_cvd_info)


def test_fetch_cvd_info_reads_cvd_and_all_its_villages(mis_cvds):
    village = mis_cvds['villages']['kpekpe_centre']
    cvds, names = real_fetch_cvd_info([str(village.id)])

    assert names == {str(village.id): 'KPEKPE CENTRE'}
    assert len(cvds) == 1 and cvds[0]['id'] == mis_cvds['named'].id and cvds[0]['name'] == 'KPEKPE'
    assert {n for _, n in cvds[0]['villages']} == {'KPEKPE CENTRE', 'KPEKPE NORD'}


def test_cvd_without_name_is_labelled_with_its_villages(django_user_model, mis_cvds):
    v = mis_cvds['villages']
    member = make_user(django_user_model, 'cvgp_bola', ['CVGPMembers'], [str(v['bola'].id)])

    info = services.resolve_member_cvd(member)

    assert info['cvd_id'] == mis_cvds['unnamed'].id
    assert info['cvd_name'] == 'BOLA/PILOUGOU'
    assert set(info['village_ids']) == {str(v['bola'].id), str(v['pilougou'].id)}
    assert info['warning'] == ''


def test_campaign_generation_against_real_mis(django_user_model, mis_cvds):
    v = mis_cvds['villages']
    ok = make_user(django_user_model, 'cvgp_ok', ['CVGPMembers'], [str(v['kpekpe_nord'].id)])
    two_cvds = make_user(django_user_model, 'cvgp_two', ['CVGPMembers'], [str(v['kpekpe_nord'].id), str(v['bola'].id)])
    no_cvd = make_user(django_user_model, 'cvgp_orphan', ['CVGPMembers'], [str(v['orphan'].id)])
    campaign = InternetCreditCampaign.objects.create(period=datetime.date(2026, 9, 1), sent_date=datetime.date(2026, 9, 2))

    stats = services.sync_campaign_beneficiaries(campaign)

    assert stats['created'] == 3
    line = InternetCreditBeneficiary.objects.get(campaign=campaign, cvgp_member=ok)
    assert line.cvd_name == 'KPEKPE' and line.village_names == 'KPEKPE CENTRE, KPEKPE NORD'
    assert line.cvgp_message.startswith('CVGP du CVD KPEKPE a bien reçu')
    # Anomalies signalées sur le web, sans bloquer la génération (le membre reçoit son forfait).
    assert '2 CVD' in InternetCreditBeneficiary.objects.get(campaign=campaign, cvgp_member=two_cvds).resolution_warning
    assert InternetCreditBeneficiary.objects.get(campaign=campaign, cvgp_member=no_cvd).resolution_warning == 'Aucun CVD trouvé'
    assert len(stats['warnings']) == 2
