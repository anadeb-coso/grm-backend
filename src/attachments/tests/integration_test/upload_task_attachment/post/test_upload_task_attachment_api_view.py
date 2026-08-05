from django.conf import settings
from parameterized import parameterized
from rest_framework.reverse import reverse

from authentication.tests import TaskFactory
from client import COUCHDB_PASSWORD, COUCHDB_USERNAME
from grm.tests import BaseTestCase
from issue.models import Attachment


class TestUploadTaskAttachmentAPIView(BaseTestCase):
    error_messages = {
        'credentials': 'Unauthorized access with the credentials provided.',
        'not_found': 'Not found.',
        'min_value': 'Ensure this value is greater than or equal to %(min_value)d.',
        'blank': 'This field may not be blank.',
        'invalid_integer': 'A valid integer is required.',
        'invalid_file': 'The submitted data was not a file. Check the encoding type on the form.',
        'required_field': 'This field is required.',
        'required_file': 'No file was submitted.',
        'file_size': 'Select a file size less than or equal to %(max_size)s. The selected file size is %(size)s.'
    }

    def setUp(self):
        super().setUp()
        self.url = reverse('attachments:upload-task-attachment')

    @parameterized.expand([
        ('wrong_username', 'wrong_password'),
        (COUCHDB_USERNAME, 'wrong_password'),
        ('wrong_username', COUCHDB_PASSWORD),
    ])
    def test_auth_permission(self, username, password):
        task = TaskFactory()
        input_data = {
            'username': username,
            'password': password,
            'doc_id': str(task.phase.adl.pk),
            'phase': 1,
            'task': 1,
            'attachment_id': 'x',
            'file': self.create_file(),
        }

        response = self.post(self.url, input_data, authorized=False, format='multipart')
        data = response.data

        assert response.status_code == 400
        assert len(data) == 1
        assert str(data['non_field_errors'][0]) == self.error_messages['credentials']

    def test_successful_upload(self):
        task = TaskFactory()
        file = self.create_file()
        input_data = {
            'username': COUCHDB_USERNAME,
            'password': COUCHDB_PASSWORD,
            'doc_id': str(task.phase.adl.pk),
            'phase': 1,
            'task': 1,
            'attachment_id': 'x',
            'file': file,
        }

        response = self.post(self.url, input_data, authorized=False, format='multipart')
        data = response.data

        assert response.status_code == 201
        assert data['ok'] is True
        attachment = Attachment.objects.get(pk=data['id'])
        assert attachment.task_id == task.pk

    def test_non_existent_doc_id(self):
        task = TaskFactory()
        input_data = {
            'username': COUCHDB_USERNAME,
            'password': COUCHDB_PASSWORD,
            'doc_id': 'non_existent_doc_id',
            'phase': 1,
            'task': 1,
            'attachment_id': 'x',
            'file': self.create_file(),
        }

        response = self.post(self.url, input_data, authorized=False, format='multipart')
        data = response.data

        assert response.status_code == 404
        assert len(data) == 1
        assert str(data['detail']) == self.error_messages['not_found']

    def test_non_existent_phase(self):
        task = TaskFactory()
        input_data = {
            'username': COUCHDB_USERNAME,
            'password': COUCHDB_PASSWORD,
            'doc_id': str(task.phase.adl.pk),
            'phase': 2,
            'task': 1,
            'attachment_id': 'x',
            'file': self.create_file(),
        }

        response = self.post(self.url, input_data, authorized=False, format='multipart')
        data = response.data

        assert response.status_code == 404
        assert len(data) == 1
        assert str(data['detail']) == self.error_messages['not_found']

    def test_non_existent_task(self):
        task = TaskFactory()
        input_data = {
            'username': COUCHDB_USERNAME,
            'password': COUCHDB_PASSWORD,
            'doc_id': str(task.phase.adl.pk),
            'phase': 1,
            'task': 2,
            'attachment_id': 'x',
            'file': self.create_file(),
        }

        response = self.post(self.url, input_data, authorized=False, format='multipart')
        data = response.data

        assert response.status_code == 404
        assert len(data) == 1
        assert str(data['detail']) == self.error_messages['not_found']

    def test_invalid_values(self):
        task = TaskFactory()
        input_data = {
            'username': COUCHDB_USERNAME,
            'password': COUCHDB_PASSWORD,
            'doc_id': str(task.phase.adl.pk),
            'phase': -1,
            'task': -1,
            'attachment_id': 'x',
            'file': self.create_file(),
        }

        response = self.post(self.url, input_data, authorized=False, format='multipart')
        data = response.data

        assert response.status_code == 400
        assert set(data.keys()) == {'phase', 'task'}
        for k in data:
            assert str(data[k][0]) == self.error_messages['min_value'] % {'min_value': 1}

    def test_empty_field(self):
        input_data = {
            'username': '',
            'password': '',
            'doc_id': '',
            'phase': '',
            'task': '',
            'attachment_id': '',
            'file': '',
        }

        response = self.post(self.url, input_data, authorized=False, format='multipart')
        data = response.data

        assert response.status_code == 400
        assert set(data.keys()) == {'username', 'password', 'file', 'doc_id', 'phase', 'task', 'attachment_id'}
        for k in {'username', 'password', 'doc_id', 'attachment_id'}:
            assert str(data[k][0]) == self.error_messages['blank']
        for k in {'phase', 'task'}:
            assert str(data[k][0]) == self.error_messages['invalid_integer']
        assert str(data['file'][0]) == self.error_messages['invalid_file']

    def test_empty_data(self):
        response = self.post(self.url, {}, authorized=False, format='multipart')
        data = response.data

        assert response.status_code == 400
        assert set(data.keys()) == {'username', 'password', 'file', 'doc_id', 'phase', 'task', 'attachment_id'}
        for k in data:
            if k != 'file':
                assert str(data[k][0]) == self.error_messages['required_field']
        assert str(data['file'][0]) == self.error_messages['required_file']

    @parameterized.expand([
        ('5.0 MB', settings.MAX_UPLOAD_SIZE),
        ('5.1 MB', settings.MAX_UPLOAD_SIZE + int(0.1 * 1024 * 1024)),
    ])
    def test_file_size(self, size_representation, size):
        task = TaskFactory()
        file = self.create_file(size)
        input_data = {
            'username': COUCHDB_USERNAME,
            'password': COUCHDB_PASSWORD,
            'doc_id': str(task.phase.adl.pk),
            'phase': 1,
            'task': 1,
            'attachment_id': 'x',
            'file': file,
        }

        response = self.post(self.url, input_data, authorized=False, format='multipart')
        data = response.data

        if size_representation == '5.0 MB':
            assert response.status_code == 201
        else:
            assert response.status_code == 400
            assert len(data) == 1
            assert str(data['file'][0]) == self.error_messages['file_size'] % {'max_size': '5.0\xa0MB',
                                                                               'size': '5.1\xa0MB'}
