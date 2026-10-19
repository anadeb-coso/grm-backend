import pytest
from rest_framework.test import APIClient

from authentication.models import GovernmentWorker, User
from authentication.utils import get_validation_code
from dashboard.grm.serializers import _citizen_type_int
from issue.models import Adl

pytestmark = pytest.mark.django_db

PASSWORD = 'pass1234'


@pytest.fixture(autouse=True)
def no_cdd_call(monkeypatch):
    """La sauvegarde d'un `GovernmentWorker` notifie l'application CDD externe
    (authentication.utils.set_user_government_worker_adl) : jamais d'appel réseau ici."""
    monkeypatch.setattr('authentication.utils.update_user_adl_on_cdd_app', lambda *args, **kwargs: None)


def _token(login, password=PASSWORD):
    return APIClient().post('/api/auth/token/', {'username': login, 'password': password})


def _user_without_username(email):
    """Comme un compte créé depuis le dashboard ou par import de fichier : `User.save` lui
    attribue un `username` aléatoire."""
    user = User(email=email, first_name='Ama', last_name='Koffi')
    user.set_password(PASSWORD)
    user.save()
    return user


def test_token_accepts_email_of_account_with_random_username():
    user = _user_without_username('agent.web@example.com')
    assert user.username != user.email

    response = _token('agent.web@example.com')

    assert response.status_code == 200, response.data
    assert response.data['access']


def test_mobile_signup_then_token_with_email():
    """Parcours de l'inscription mobile (SignUp.js) : `/authentication/register/` puis connexion
    automatique par e-mail, pour un compte créé sans `username` (dashboard, import)."""
    email = 'nouvel.agent@example.com'
    password = 'p' * 16
    user = User(email=email, first_name='Nouvel', last_name='Agent')  # sans mot de passe : jamais inscrit
    user.save()
    GovernmentWorker.objects.create(user=user, department=1, administrative_id='1', administrative_ids=[])

    register = APIClient().post(
        '/authentication/register/',
        {'email': email, 'password': password, 'validation_code': get_validation_code(email)},
        format='json',
    )

    assert register.status_code == 201, register.data
    assert _token(email, password).status_code == 200


def test_token_email_lookup_is_case_insensitive():
    _user_without_username('agent.web@example.com')

    assert _token('Agent.Web@Example.com').status_code == 200


def test_token_still_accepts_username_and_rejects_wrong_password():
    User.objects.create_user(username='agent', email='agent@example.com', password=PASSWORD)

    assert _token('agent').status_code == 200
    assert _token('agent@example.com', 'mauvais-mot').status_code == 401


def _profile(user):
    client = APIClient()
    client.force_authenticate(user=user)
    response = client.get('/authentication/me/')
    assert response.status_code == 200, response.data
    return response.data['eadl']


def test_profile_of_national_account_without_localities_is_national():
    """`administrative_id` = "1" mais `administrative_ids` vide : le mobile doit recevoir
    `administrative_region` = "1" pour afficher toutes les plaintes (compte Admin)."""
    user = _user_without_username('admin.national@example.com')
    GovernmentWorker.objects.create(user=user, department=1, administrative_id='1', administrative_ids=[])

    assert _profile(user)['administrative_region'] == '1'


def test_profile_keeps_first_locality_when_present():
    user = _user_without_username('facilitatrice@example.com')
    GovernmentWorker.objects.create(user=user, department=1, administrative_id='4607', administrative_ids=[])
    Adl.objects.filter(representative=user).update(administrative_region_ids=['4589', '4607'])

    assert _profile(user)['administrative_region'] == '4589'


@pytest.mark.parametrize('stored, expected', [('1', 1), ('3', 3), ('0', 0), (None, None), ('', None), ('x', None)])
def test_citizen_type_is_an_int_in_legacy_issue_dict(stored, expected):
    """Les templates comparent `doc.citizen_type == 1` (nom confidentiel masqué)."""
    assert _citizen_type_int(stored) == expected
