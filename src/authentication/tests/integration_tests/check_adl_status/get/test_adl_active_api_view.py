from parameterized import parameterized
from rest_framework.reverse import reverse

from authentication.tests import UserFactory
from grm.tests import BaseTestCase


class TestADLActiveAPIView(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.url = reverse('authentication:check_adl_status')

    @parameterized.expand([
        (True,),
        (False,),
    ])
    def test_valid_user(self, is_active):
        user = UserFactory(is_active=is_active)

        response = self.get(self.url, {'email': user.email}, authorized=False)
        data = response.data

        assert response.status_code == 200
        assert len(data) == 1
        assert data['is_active'] == is_active

    def test_empty_field(self):
        input_data = {
            'email': '',
        }

        response = self.get(self.url, input_data, authorized=False)
        data = response.data

        assert response.status_code == 404
        assert len(data) == 1

    def test_empty_data(self):
        input_data = {}

        response = self.get(self.url, input_data, authorized=False)
        data = response.data

        assert response.status_code == 404
        assert len(data) == 1

    def test_no_user_for_email(self):
        user = UserFactory()
        input_data = {
            'email': f'other_{user.email}',
        }

        response = self.get(self.url, input_data, authorized=False)
        data = response.data

        assert response.status_code == 404
        assert len(data) == 1
