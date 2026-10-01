import logging

try:
    from grm.settings import *  # noqa
except ImportError:
    pass

MIDDLEWARE = [
    middleware for middleware in MIDDLEWARE if middleware not in [  # noqa: F405
        'django.middleware.security.SecurityMiddleware',
        'corsheaders.middleware.CorsMiddleware',
        'django.middleware.common.CommonMiddleware',
        'django.middleware.csrf.CsrfViewMiddleware',
        'django.middleware.clickjacking.XFrameOptionsMiddleware'
    ]
]

INSTALLED_APPS = [
    app for app in INSTALLED_APPS if app not in [  # noqa: F405
        'django.contrib.staticfiles'
    ]
]

PASSWORD_HASHERS = (
    'django.contrib.auth.hashers.MD5PasswordHasher',
)

MEDIA_URL = '/media/'

logging.disable(logging.CRITICAL)

COUCHDB_DATABASE = COUCHDB_GRM_DATABASE = COUCHDB_ATTACHMENT_DATABASE = COUCHDB_GRM_ATTACHMENT_DATABASE = 'test'

# Les tests vérifient des messages d'erreur rédigés en anglais (langue source des chaînes
# traduites) : on fige donc la langue des tests, indépendamment de LANGUAGE_CODE du `.env`
# (`fr` en exploitation). Le français reste disponible pour les tests qui le demandent
# explicitement (URL préfixée `/fr/` ou `translation.override('fr')`).
LANGUAGE_CODE = 'en'
LANGUAGES = [('en', 'English'), ('fr', 'French')]

# Base `mis` de TEST (référentiel administratif de `cosomis`, cf. grm/routers.py) : une base
# jetable dédiée, créée puis supprimée par le test runner, dont les tables
# `administrativelevels_*` sont créées par le conftest racine (src/conftest.py) puisque cette
# app n'a aucune migration ici. Les tests qui en ont besoin la déclarent explicitement
# (`databases = {'default', 'mis'}` ou `pytest.mark.django_db(databases=[...])`) ; les autres
# continuent de mocker `AdministrativeLevel` (voir sync/tests/test_sync.py).
#
# ⚠️ Incident documenté dans grm/routers.py : un `TEST NAME` égal au nom réel a causé un DROP
# DATABASE de la vraie base `mis`, le test runner supprimant puis recréant sa base de test à
# chaque run. Le nom de test est donc explicite, distinct, et vérifié ci-dessous.
MIS_TEST_DATABASE_NAME = 'test_grm_mis'
_mis = DATABASES.get(EXTERNAL_DATABASE_NAME)  # noqa: F405
DATABASES = {'default': DATABASES['default']}  # noqa: F405
if _mis:
    if _mis.get('NAME') == MIS_TEST_DATABASE_NAME or not MIS_TEST_DATABASE_NAME.startswith('test_'):
        raise RuntimeError('Nom de base de test `mis` dangereux : il doit être distinct de la vraie base.')
    DATABASES[EXTERNAL_DATABASE_NAME] = {**_mis, 'TEST': {'NAME': MIS_TEST_DATABASE_NAME}}  # noqa: F405
