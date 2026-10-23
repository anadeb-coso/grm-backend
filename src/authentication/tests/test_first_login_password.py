"""Mot de passe initial des comptes créés dans le DCC : obligation lue dans la table du DCC (base `mis`), refus
du jeton mobile, page web imposée, et compte MGP d'un facilitateur créé par le DCC (`api/service/users/facilitator/`)."""
import pytest
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core import mail
from django.db import connections
from django.test import Client, override_settings
from rest_framework.test import APIClient

from django.urls import reverse

from administrativelevels.models import AdministrativeLevel
from authentication.models import GovernmentWorker, User
from authentication.password_change import password_change_required
from issue.models import Adl

pytestmark = pytest.mark.django_db(databases=['default', 'mis'])

PASSWORD = 'Initial234'
SERVICE = {'HTTP_X_GRM_SECRET': settings.GRM_SECRET_KEY_GENRATE}


@pytest.fixture(autouse=True)
def no_cdd_call(monkeypatch):
    """La sauvegarde d'un `GovernmentWorker` notifie le DCC : jamais d'appel réseau ici."""
    calls = []
    monkeypatch.setattr('authentication.utils.update_user_adl_on_cdd_app', lambda *args, **kwargs: calls.append((args, kwargs)))
    return calls


@pytest.fixture
def requirements():
    """Table du DCC dans la base `mis` de test (créée par le DCC en exploitation)."""
    with connections['mis'].cursor() as cursor:
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS authentication_passwordchangerequirement ("
            " id bigserial PRIMARY KEY, email varchar(254) NULL, user_id integer NULL, facilitator_id bigint NULL,"
            " created_by_id integer NULL, created_at timestamptz NOT NULL DEFAULT now(),"
            " changed_at timestamptz NULL, changed_on varchar(30) NULL)"
        )

    def add(email, changed=False):
        with connections['mis'].cursor() as cursor:
            cursor.execute(
                "INSERT INTO authentication_passwordchangerequirement (email, changed_at) VALUES (%s, "
                + ("now()" if changed else "NULL") + ")",
                [email.lower()],
            )
    return add


def make_user(email='agent.dcc@example.org', password=PASSWORD):
    user = User(email=email, first_name='Agent', last_name='DCC')
    user.set_password(password)
    user.save()
    return user


# -- lecture de l'obligation ----------------------------------------------------------------------

def test_requirement_is_read_from_the_shared_table(requirements):
    assert not password_change_required('agent.dcc@example.org')
    requirements('agent.dcc@example.org')
    assert password_change_required('Agent.DCC@Example.org')
    assert not password_change_required('autre@example.org')
    assert not password_change_required('')
    requirements('deja.change@example.org', changed=True)
    assert not password_change_required('deja.change@example.org')


def test_missing_table_never_blocks(monkeypatch):
    class BrokenConnections(dict):
        def __getitem__(self, alias):
            raise RuntimeError('base injoignable')

    monkeypatch.setattr('authentication.password_change.connections', BrokenConnections(mis=None))
    assert password_change_required('agent.dcc@example.org') is False


# -- application mobile ------------------------------------------------------------------------

def test_token_refused_with_a_code_until_the_password_is_changed(requirements):
    make_user()
    requirements('agent.dcc@example.org')
    response = APIClient().post('/api/auth/token/', {'username': 'agent.dcc@example.org', 'password': PASSWORD})
    assert response.status_code == 403
    assert response.data['code'] == 'password_change_required' and response.data['detail']
    # mauvais mot de passe : refus habituel, sans révéler l'obligation
    response = APIClient().post('/api/auth/token/', {'username': 'agent.dcc@example.org', 'password': 'Mauvais999'})
    assert response.status_code == 401


def test_token_and_profile_once_changed(requirements):
    user = make_user()
    requirements('agent.dcc@example.org', changed=True)
    response = APIClient().post('/api/auth/token/', {'username': 'agent.dcc@example.org', 'password': PASSWORD})
    assert response.status_code == 200 and response.data['access']
    client = APIClient()
    client.force_authenticate(user=user)
    assert client.get('/authentication/me/').data['password_change_required'] is False
    requirements('agent.dcc@example.org')
    assert client.get('/authentication/me/').data['password_change_required'] is True


def test_legacy_login_refused_too(requirements):
    make_user()
    requirements('agent.dcc@example.org')
    response = APIClient().post('/authentication/obtain-auth-credentials/', {'email': 'agent.dcc@example.org', 'password': PASSWORD},
                                format='json')
    assert response.status_code == 403 and response.data['code'] == 'password_change_required'


# -- page web imposée --------------------------------------------------------------------------

def test_web_pages_redirect_to_the_forced_change(requirements, monkeypatch):
    user = make_user()
    requirements('agent.dcc@example.org')
    calls = []

    def fake_cdd(email, current, new, confirmation, platform, language=None):
        calls.append((email, current, new, confirmation, platform))
        if current != PASSWORD:
            return False, 'Incorrect identifiers'
        # le DCC applique le nouveau mot de passe à ce compte MGP (api/service/users/set-password/)
        account = User.objects.get(pk=user.pk)
        account.set_password(new)
        account.save(update_fields=['password'])
        with connections['mis'].cursor() as cursor:
            cursor.execute("UPDATE authentication_passwordchangerequirement SET changed_at = now() WHERE email = %s", [email.lower()])
        return True, 'ok'

    monkeypatch.setattr('dashboard.authentication.views.change_initial_password_on_cdd', fake_cdd)
    client = Client()
    client.force_login(user)
    response = client.get(reverse('dashboard:grm:review_issues'))
    assert response.status_code == 302 and response['Location'].endswith('/en/first-login-password/')
    assert client.get('/en/first-login-password/').status_code == 200
    assert client.get(reverse('dashboard:adls:list')).status_code == 302

    response = client.post('/en/first-login-password/', {
        'current_password': 'Mauvais999', 'new_password': 'NewPass123', 'new_password_confirm': 'NewPass123'})
    assert response.status_code == 200 and b'Incorrect identifiers' in response.content

    response = client.post('/en/first-login-password/', {
        'current_password': PASSWORD, 'new_password': 'NewPass123', 'new_password_confirm': 'NewPass123'})
    assert response.status_code == 302
    assert calls[-1] == ('agent.dcc@example.org', PASSWORD, 'NewPass123', 'NewPass123', 'mgp_web')
    user.refresh_from_db()
    assert check_password('NewPass123', user.password)
    # session gardée malgré le nouveau mot de passe
    response = client.get('/en/first-login-password/')
    assert response.status_code == 302 and '/first-login-password/' not in response['Location']


def test_accounts_without_requirement_reach_their_pages(requirements):
    user = make_user()
    client = Client()
    client.force_login(user)
    response = client.get('/en/first-login-password/')
    assert response.status_code == 302 and '/first-login-password/' not in response['Location']


# -- compte MGP d'un facilitateur créé dans le DCC --------------------------------------------

def facilitator_payload(**overrides):
    payload = {
        'create': True, 'email': 'nouveau.fc@example.org', 'first_name': 'Yawa', 'last_name': 'AGBEKO',
        'phone': '22890000001', 'facilitator_type': 'community_facilitator', 'password_hash': make_password('DccPass123'),
        'is_active': True, 'administrative_id': '5833', 'administrative_ids': ['5833'], 'additional_administrative_ids': [],
    }
    payload.update(overrides)
    return payload


def test_create_facilitator_account(no_cdd_call):
    AdministrativeLevel.objects.using('mis').create(id=5833, name='ANIMA', type='Village')
    response = APIClient().post('/api/service/users/facilitator/', facilitator_payload(), format='json', **SERVICE)
    assert response.status_code == 200 and response.data['status'] == 'created', response.data
    user = User.objects.get(email='nouveau.fc@example.org')
    assert (user.first_name, user.last_name, user.phone_number) == ('Yawa', 'AGBEKO', '22890000001')
    assert check_password('DccPass123', user.password)
    assert list(user.groups.values_list('name', flat=True)) == ['CommunityFacilitator']
    worker = GovernmentWorker.objects.get(user=user)
    assert worker.administrative_id == '5833' and worker.administrative_ids == ['5833'] and worker.department == 1
    assert Adl.objects.filter(representative=user).exists()
    assert mail.outbox == []  # pas de code d'activation : identifiants déjà envoyés par le DCC
    assert no_cdd_call and no_cdd_call[-1][0][0] == 'nouveau.fc@example.org'  # villages renvoyés au DCC
    # connexion mobile avec le mot de passe du DCC
    assert APIClient().post('/api/auth/token/', {'username': 'nouveau.fc@example.org', 'password': 'DccPass123'}).status_code == 200


@override_settings(PASSWORD_HASHERS=[
    'django.contrib.auth.hashers.PBKDF2PasswordHasher', 'django.contrib.auth.hashers.MD5PasswordHasher'])
def test_create_facilitator_account_with_a_dcc_hash():
    """Empreinte au format du DCC (PBKDF2, 390 000 itérations)."""
    from django.contrib.auth.hashers import PBKDF2PasswordHasher

    dcc_hash = PBKDF2PasswordHasher().encode('DccPass123', 'saltsaltsalt1234', iterations=390000)
    response = APIClient().post('/api/service/users/facilitator/', facilitator_payload(
        email='ft.hash@example.org', facilitator_type='technical_facilitator', password_hash=dcc_hash,
        administrative_id=None, administrative_ids=[]), format='json', **SERVICE)
    assert response.status_code == 200, response.data
    user = User.objects.get(email='ft.hash@example.org')
    assert check_password('DccPass123', user.password)
    assert list(user.groups.values_list('name', flat=True)) == ['TechnicalFacilitator']
    assert GovernmentWorker.objects.get(user=user).administrative_ids == []


def test_existing_mgp_account_is_left_unchanged():
    existing = make_user('Deja.Mgp@example.org', 'MgpPass123')
    response = APIClient().post('/api/service/users/facilitator/', facilitator_payload(email='deja.mgp@example.org'),
                                format='json', **SERVICE)
    assert response.status_code == 200 and response.data == {'status': 'exists', 'id': existing.id}
    existing.refresh_from_db()
    assert check_password('MgpPass123', existing.password) and not existing.groups.exists()
    assert not GovernmentWorker.objects.filter(user=existing).exists()


def test_create_facilitator_account_refusals():
    client = APIClient()
    assert client.post('/api/service/users/facilitator/', facilitator_payload(), format='json').status_code in (401, 403)
    for overrides in ({'email': ''}, {'facilitator_type': 'autre'}, {'password_hash': 'motdepasseenclair'}):
        response = client.post('/api/service/users/facilitator/', facilitator_payload(**overrides), format='json', **SERVICE)
        assert response.status_code == 400, overrides
    assert not User.objects.filter(email='nouveau.fc@example.org').exists()


def test_update_facilitator_identity():
    APIClient().post('/api/service/users/facilitator/', facilitator_payload(), format='json', **SERVICE)
    response = APIClient().post('/api/service/users/facilitator/', {
        'create': False, 'previous_email': 'NOUVEAU.FC@example.org', 'email': 'renomme.fc@example.org',
        'first_name': 'Yawa Mawuena', 'last_name': 'AGBEKO', 'phone': '22891111111'}, format='json', **SERVICE)
    assert response.status_code == 200 and response.data['status'] == 'updated'
    user = User.objects.get(email='renomme.fc@example.org')
    assert (user.first_name, user.phone_number) == ('Yawa Mawuena', '22891111111')
    assert check_password('DccPass123', user.password)
    assert Adl.objects.get(representative=user).representative_name == 'Yawa Mawuena AGBEKO'

    make_user('occupe@example.org')
    response = APIClient().post('/api/service/users/facilitator/', {
        'create': False, 'previous_email': 'renomme.fc@example.org', 'email': 'occupe@example.org'}, format='json', **SERVICE)
    assert response.status_code == 409
    response = APIClient().post('/api/service/users/facilitator/', {
        'create': False, 'previous_email': 'inconnu@example.org', 'email': 'x@example.org'}, format='json', **SERVICE)
    assert response.status_code == 404


def test_set_password_finds_the_account_whatever_the_case():
    user = make_user('Casse.Mixte@example.org')
    response = APIClient().post('/api/service/users/set-password/', {'email': 'casse.mixte@example.org', 'new_password': 'Autre1234'},
                                format='json', **SERVICE)
    assert response.status_code == 200
    user.refresh_from_db()
    assert check_password('Autre1234', user.password)
