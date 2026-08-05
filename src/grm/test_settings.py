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

# `mis` (MySQL, base externe du projet `cosomis`) est volontairement absente des DATABASES de
# test : elle n'a aucune migration ici (voir grm/routers.py) et le test runner Django tenterait
# malgré tout de lui construire un plan de migration multi-base, ce qui échoue puisque l'app
# `administrativelevels` n'existe dans aucun historique de migrations. Les tests qui ont besoin
# d'un `AdministrativeLevel` mockent l'accès au modèle (voir sync/tests/test_sync.py) plutôt que
# d'ouvrir une vraie connexion vers `mis` — voir aussi l'incident documenté dans grm/routers.py
# qui a motivé cette exclusion stricte.
DATABASES = {'default': DATABASES['default']}  # noqa: F405
