import json
import tempfile

import pytest
from rest_framework.test import APITestCase

from authentication.tests import UserFactory

JSON_TYPE = 'application/json'
URLENCODED_TYPE = 'application/x-www-form-urlencoded'
AJAX_HEADER = 'HTTP_X_REQUESTED_WITH'
AJAX_HEADER_VALUE = 'XMLHttpRequest'


@pytest.mark.django_db
class BaseTestCase(APITestCase):
    """`tearDown` nettoyait auparavant la base CouchDB `eadls` après chaque test (les écritures
    CouchDB, contrairement à Postgres, n'étaient pas couvertes par le rollback automatique de
    `pytest.mark.django_db`). Toutes les données créées pendant les tests vivent désormais dans
    Postgres, déjà isolées/rollback automatiquement par ce marqueur : plus besoin de nettoyage
    manuel."""
    rest = True
    content_type = JSON_TYPE
    user = None

    @staticmethod
    def create_user(is_active=True, **kwargs):
        return UserFactory(is_active=is_active)

    @staticmethod
    def create_file(size=1):
        fp = tempfile.NamedTemporaryFile()
        fp.write(bytes(size))
        fp.seek(0)
        return fp

    def authenticate(self, user):
        self.user = self.create_user() if not self.user else self.user
        request_user = user if user else self.user
        if self.rest:
            self.client.force_authenticate(user=request_user)
        else:
            self.client.force_login(user=request_user)

    def get(self, uri, data=None, authorized=True, user=None, ajax=None, **kwargs):
        if authorized:
            self.authenticate(user)
        elif self.rest:
            self.client.force_authenticate(user=None)
        if ajax:
            kwargs[AJAX_HEADER] = AJAX_HEADER_VALUE
        return self.client.get(uri, data, **kwargs)

    def put(self, uri, data, authorized=True, user=None, ajax=None, **kwargs):
        self.client.logout()
        if authorized:
            self.authenticate(user)
        if self.content_type == JSON_TYPE:
            data = json.dumps(data)
            kwargs['content_type'] = self.content_type
        if ajax:
            kwargs[AJAX_HEADER] = AJAX_HEADER_VALUE
        return self.client.put(uri, data, **kwargs)

    def patch(self, uri, data, authorized=True, user=None, ajax=None, **kwargs):
        self.client.logout()
        if authorized:
            self.authenticate(user)
        if self.content_type == JSON_TYPE:
            data = json.dumps(data)
            kwargs['content_type'] = self.content_type
        if ajax:
            kwargs[AJAX_HEADER] = AJAX_HEADER_VALUE
        return self.client.patch(uri, data, **kwargs)

    def post(self, uri, data, authorized=True, user=None, ajax=None, **kwargs):
        self.client.logout()
        if authorized:
            self.authenticate(user)
        if self.content_type == JSON_TYPE:
            if 'format' not in kwargs:
                data = json.dumps(data)
                kwargs['content_type'] = self.content_type
        if ajax:
            kwargs[AJAX_HEADER] = AJAX_HEADER_VALUE
        return self.client.post(uri, data, **kwargs)

    def delete(self, uri, authorized=True, user=None, ajax=None, **kwargs):
        self.client.logout()
        if authorized:
            self.authenticate(user)
        if ajax:
            kwargs[AJAX_HEADER] = AJAX_HEADER_VALUE
        return self.client.delete(uri, **kwargs)


class DashboardTestCase(BaseTestCase):
    rest = False
    content_type = URLENCODED_TYPE
