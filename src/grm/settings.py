"""
Django settings for grm project.

Generated by 'django-admin startproject' using Django 3.2.9.

For more information on this file, see
https://docs.djangoproject.com/en/3.2/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/3.2/ref/settings/
"""

from pathlib import Path

import django.conf.locale
import environ
from django.conf import global_settings
from django.utils.translation import gettext_lazy as _

# https://django-environ.readthedocs.io/en/latest/
env = environ.Env()
env.read_env()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/3.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = env('SECRET_KEY')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env.bool('DEBUG', False)

ALLOWED_HOSTS = env('ALLOWED_HOSTS', list, ['localhost'])

# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

CREATED_APPS = [
    'attachments',
    'authentication',
    'dashboard',
]

THIRD_PARTY_APPS = [
    'bootstrap4',
    'drf_yasg',
    'rest_framework',
    'django_celery_results'
]

INSTALLED_APPS += CREATED_APPS + THIRD_PARTY_APPS

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'grm.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'dashboard.context_processors.settings_vars',
            ],
        },
    },
]

WSGI_APPLICATION = 'grm.wsgi.application'

# Database
# https://docs.djangoproject.com/en/3.2/ref/settings/#databases
DATABASES = {
    'default': env.db(default='sqlite:///grm.db')
}

# Password validation
# https://docs.djangoproject.com/en/3.2/ref/settings/#auth-password-validators
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {
            'min_length': 8,
        }
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
# https://docs.djangoproject.com/en/3.2/topics/i18n/
LANGUAGE_CODE = env('LANGUAGE_CODE', default='en-us')

TIME_ZONE = 'UTC'

USE_I18N = True

USE_L10N = True

USE_TZ = True

OTHER_LANGUAGES = env('OTHER_LANGUAGES', list, default=[])

LANGUAGES = (
    ('en-us', _('English')),
    ('fr', _('French')),
    ('rw', _('Kinyarwanda')),
)
LANGUAGES = [lang for lang in LANGUAGES if lang[0] in OTHER_LANGUAGES or lang[0] == LANGUAGE_CODE]

# Add custom languages not provided by Django
EXTRA_LANG_INFO = {
    'rw': {
        'bidi': True,
        'code': 'rw',
        'name': 'Kinyarwanda',
        'name_local': 'Kinyarwanda',
    },
}

LANG_INFO = dict(django.conf.locale.LANG_INFO, **EXTRA_LANG_INFO)
django.conf.locale.LANG_INFO = LANG_INFO

# Languages using BiDi (right-to-left) layout
LANGUAGES_BIDI = global_settings.LANGUAGES_BIDI + ["rw"]

LOCALE_PATHS = [
    BASE_DIR / "locale",
]

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/3.1/howto/static-files/
STATIC_URL = '/static/'

STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_ROOT = BASE_DIR / 'media/'

MEDIA_URL = '/media/'

MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # 5MB

AUTH_USER_MODEL = 'authentication.User'

# Default primary key field type
# https://docs.djangoproject.com/en/3.2/ref/settings/#default-auto-field
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# AUTHENTICATION_BACKENDS = ('grm.backends.EmailModelBackend',)

LOGIN_URL = '/'

LOGIN_REDIRECT_URL = 'dashboard:diagnostics:home'

LOGOUT_REDIRECT_URL = '/'

# CouchDB
COUCHDB_DATABASE = env('COUCHDB_DATABASE')

COUCHDB_ATTACHMENT_DATABASE = env('COUCHDB_ATTACHMENT_DATABASE')

COUCHDB_GRM_DATABASE = env('COUCHDB_GRM_DATABASE')

COUCHDB_GRM_ATTACHMENT_DATABASE = env('COUCHDB_GRM_ATTACHMENT_DATABASE')

COUCHDB_URL = env('COUCHDB_URL')

COUCHDB_USERNAME = env('COUCHDB_USERNAME')

COUCHDB_PASSWORD = env('COUCHDB_PASSWORD')

DATE_INPUT_FORMATS = [
    '%d-%m-%Y', '%d/%m/%Y', '%d/%m/%y',  # '25-10-2006', '25/10/2006', '25/10/06'
    '%d %b %Y', '%d %b, %Y',  # '25 Oct 2006', '25 Oct, 2006'
    '%d %B %Y', '%d %B, %Y',  # '25 October 2006', '25 October, 2006'
]

# Celery settings
CELERY_BROKER_URL = env('CELERY_BROKER_URL')

#: Only add pickle to this list if your broker is secured
#: from unwanted access (see userguide/security.html)

CELERY_ACCEPT_CONTENT = ['json']

CELERY_RESULT_BACKEND = 'django-db'

CELERY_TASK_SERIALIZER = 'json'

# Mapbox
MAPBOX_ACCESS_TOKEN = env('MAPBOX_ACCESS_TOKEN')

DIAGNOSTIC_MAP_LATITUDE = env('DIAGNOSTIC_MAP_LATITUDE')

DIAGNOSTIC_MAP_LONGITUDE = env('DIAGNOSTIC_MAP_LONGITUDE')

DIAGNOSTIC_MAP_ZOOM = env('DIAGNOSTIC_MAP_ZOOM')

DIAGNOSTIC_MAP_WS_BOUND = env('DIAGNOSTIC_MAP_WS_BOUND')

DIAGNOSTIC_MAP_EN_BOUND = env('DIAGNOSTIC_MAP_EN_BOUND')

DIAGNOSTIC_MAP_ISO_CODE = env('DIAGNOSTIC_MAP_ISO_CODE')

# Twilio
# https://www.twilio.com/docs
TWILIO_ACCOUNT_SID = env('TWILIO_ACCOUNT_SID')

TWILIO_AUTH_TOKEN = env('TWILIO_AUTH_TOKEN')

TWILIO_FROM_NUMBER = env('TWILIO_FROM_NUMBER')
