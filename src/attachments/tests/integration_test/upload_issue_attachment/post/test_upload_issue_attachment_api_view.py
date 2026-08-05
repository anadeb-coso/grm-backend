from rest_framework.reverse import reverse

from authentication.tests import IssueFactory
from client import COUCHDB_PASSWORD, COUCHDB_USERNAME
from grm.tests import BaseTestCase
from issue.models import Attachment


class TestUploadIssueAttachmentAPIView(BaseTestCase):
    """`UploadIssueAttachmentAPIView` ne valide plus (et ne validait déjà pas, la validation par
    `IssueFileSerializer` étant commentée dans le code CouchDB d'origine) les champs
    `username`/`password`/`attachment_id` : seul un `file` est requis, cf. attachments/views.py."""

    error_messages = {
        'not_found': 'Not found.',
    }

    def setUp(self):
        super().setUp()
        self.url = reverse('attachments:upload-issue-attachment')

    def test_successful_upload(self):
        issue = IssueFactory()
        file = self.create_file()

        response = self.post(self.url, {
            'username': COUCHDB_USERNAME, 'password': COUCHDB_PASSWORD,
            'doc_id': str(issue.pk), 'attachment_id': 'x', 'file': file,
        }, authorized=False, format='multipart')
        data = response.data

        assert response.status_code == 201
        assert data['message'] == 'OK'
        assert data['bd_id']

        attachment = Attachment.objects.get(pk=data['bd_id'])
        assert attachment.issue_id == issue.pk
        assert attachment.url == data['fileUrl']

    def test_upload_without_doc_id(self):
        file = self.create_file()

        response = self.post(self.url, {
            'username': COUCHDB_USERNAME, 'password': COUCHDB_PASSWORD,
            'attachment_id': 'x', 'file': file,
        }, authorized=False, format='multipart')
        data = response.data

        assert response.status_code == 201
        attachment = Attachment.objects.get(pk=data['bd_id'])
        assert attachment.issue_id is None

    def test_non_existent_doc_id(self):
        response = self.post(self.url, {
            'username': COUCHDB_USERNAME, 'password': COUCHDB_PASSWORD,
            'doc_id': 'non_existent_doc_id', 'attachment_id': 'x', 'file': self.create_file(),
        }, authorized=False, format='multipart')
        data = response.data

        assert response.status_code == 404
        assert str(data['detail']) == self.error_messages['not_found']

    def test_no_file(self):
        issue = IssueFactory()

        response = self.post(self.url, {
            'username': COUCHDB_USERNAME, 'password': COUCHDB_PASSWORD,
            'doc_id': str(issue.pk), 'attachment_id': 'x',
        }, authorized=False, format='multipart')
        data = response.data

        assert response.status_code == 404
        assert str(data['detail']) == self.error_messages['not_found']
