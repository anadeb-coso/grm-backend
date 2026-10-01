import datetime
import uuid

import pytest
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

from internet_credits import services
from internet_credits.models import InternetCreditCampaign
from issue.models import Adl

SIGNATURE = (
    'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='
)

# CVD fictifs (la base `mis` n'est jamais ouverte en test, cf. grm/test_settings.py).
FAKE_CVDS = {
    '101': {'id': 7001, 'name': 'KPEKPE', 'villages': [('101', 'Kpekpe Centre'), ('102', 'Kpekpe Nord')]},
    '102': {'id': 7001, 'name': 'KPEKPE', 'villages': [('101', 'Kpekpe Centre'), ('102', 'Kpekpe Nord')]},
    '301': {'id': 7002, 'name': 'DAPAONG', 'villages': [('301', 'Dapaong')]},
}


@pytest.fixture(autouse=True)
def fake_mis(monkeypatch):
    def _fetch_cvd_info(village_ids):
        cvds = {}
        for village_id in village_ids:
            cvd = FAKE_CVDS.get(str(village_id))
            if cvd:
                cvds[cvd['id']] = cvd
        return list(cvds.values()), {str(v): f'Village {v}' for v in village_ids}

    monkeypatch.setattr(services, 'fetch_cvd_info', _fetch_cvd_info)


def make_user(django_user_model, username, groups=(), villages=None):
    user = django_user_model.objects.create_user(
        username=username, email=f'{username}@example.com', password='pass1234',
        first_name=username.capitalize(), phone_number='22890000000',
    )
    for name in groups:
        user.groups.add(Group.objects.get_or_create(name=name)[0])
    if villages is not None:
        Adl.objects.create(
            name='Village', representative=user,
            administrative_region_ids=villages, smallest_administrative_level_ids=villages,
        )
    return user


def api_client(user):
    client = APIClient()
    resp = client.post('/api/auth/token/', {'username': user.username, 'password': 'pass1234'})
    assert resp.status_code == 200, resp.data
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
    return client


@pytest.fixture
def actors(django_user_model):
    return {
        'cvgp': make_user(django_user_model, 'cvgp1', ['CVGPMembers'], ['101', '102']),
        'cvgp_other': make_user(django_user_model, 'cvgp2', ['CVGPMembers'], ['301']),
        'fc': make_user(django_user_model, 'fc1', ['CommunityFacilitator'], ['102', '200']),
        'fc_out': make_user(django_user_model, 'fc2', ['CommunityFacilitator'], ['999']),
        'nobody': make_user(django_user_model, 'nobody', [], ['101']),
    }


@pytest.fixture
def campaign():
    campaign = InternetCreditCampaign.objects.create(
        period=datetime.date(2026, 9, 17), sent_date=datetime.date(2026, 9, 2),
    )
    services.sync_campaign_beneficiaries(campaign)
    return campaign


def confirmation_record(beneficiary, **overrides):
    record = {
        'id': str(uuid.uuid4()),
        'beneficiary': str(beneficiary.id),
        'checked': True,
        'signature': SIGNATURE,
        'description': '',
        'message': '',
        'confirmed_at': '2026-09-20T10:00:00.000Z',
        '_status': 'created',
        '_changed': '',
    }
    record.update(overrides)
    return record
