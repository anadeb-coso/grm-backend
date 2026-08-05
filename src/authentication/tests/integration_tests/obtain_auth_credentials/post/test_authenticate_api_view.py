from django.contrib.auth.hashers import make_password
from parameterized import parameterized
from rest_framework.reverse import reverse

from authentication.tests import UserFactory
from grm.tests import BaseTestCase


class TestAuthenticateAPIView(BaseTestCase):
    error_messages = {
        'invalid': 'Invalid data. Expected a dictionary, but got {datatype}.',
        'credentials': 'Unable to log in with provided credentials.',
        'is_required': 'This field is required.',
        'may_not_be_blank': 'This field may not be blank.',
    }

    def setUp(self):
        super().setUp()
        self.url = reverse('authentication:obtain_auth_credentials')

    def test_successful_login(self):
        password = 'p4ssw0rd'
        user = UserFactory(password=make_password(password))
        input_data = {
            'password': password,
            'email': user.email,
        }

        response = self.post(self.url, input_data, authorized=False)
        data = response.data

        assert response.status_code == 200
        assert len(data) == 2
        assert data['doc_id'] == str(user.id)

    def test_invalid_password(self):
        password = 'p4ssw0rd'
        user = UserFactory(password=make_password(password))
        input_data = {
            'password': password.upper(),
            'email': user.email,
        }

        response = self.post(self.url, input_data, authorized=False)
        data = response.data

        assert response.status_code == 400
        assert len(data) == 1
        assert str(data['non_field_errors'][0]) == self.error_messages['credentials']

    def test_empty_field(self):
        input_data = {
            'password': '',
            'email': '',
        }

        response = self.post(self.url, input_data, authorized=False)
        data = response.data

        assert response.status_code == 400
        assert {k for k in data} == {'password', 'email'}
        for k in data:
            assert str(data[k][0]) == self.error_messages['may_not_be_blank']

    def test_empty_data(self):
        input_data = {}

        response = self.post(self.url, input_data, authorized=False)
        data = response.data

        assert response.status_code == 400
        assert {k for k in data} == {'password', 'email'}
        for k in data:
            assert str(data[k][0]) == self.error_messages['is_required']

    def test_no_user_for_email(self):
        user = UserFactory()
        input_data = {
            'password': '12345678',
            'email': f'other_{user.email}',
        }

        response = self.post(self.url, input_data, authorized=False)
        data = response.data

        assert response.status_code == 400
        assert len(data) == 1
        assert str(data['non_field_errors'][0]) == self.error_messages['credentials']

    @parameterized.expand([
        ('a', 'str'),
        (1, 'int'),
        (1.0, 'float'),
        ([], 'list'),
        ((), 'list'),
    ])
    def test_invalid_data(self, input_data, data_type):
        response = self.post(self.url, input_data, authorized=False)
        data = response.data

        assert response.status_code == 400
        assert len(data) == 1
        assert data['non_field_errors'][0] == self.error_messages['invalid'].format(datatype=data_type)

    def test_inactive_user(self):
        password = 'p4ssw0rd'
        inactive_user = UserFactory(password=make_password(password), is_active=False)
        input_data = {
            'password': password,
            'email': inactive_user.email,
        }

        response = self.post(self.url, input_data, authorized=False)
        data = response.data

        assert response.status_code == 400
        assert len(data) == 1
        assert str(data['non_field_errors'][0]) == self.error_messages['credentials']
