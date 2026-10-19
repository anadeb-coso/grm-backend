import re
import uuid
from pathlib import Path

import pytest
from django.conf import settings
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import query as query_module
from django.urls import reverse
from django.utils import timezone, translation

from administrativelevels.models import AdministrativeLevel
from authentication.models import User
from issue.models import Attachment, Issue, IssueCategory, IssueStatus, IssueType

# Constats du guide web MGP : pièce jointe en erreur 500 hors assistant d'enregistrement,
# corbeille sans confirmation, photo de compte cassée, page Profil en anglais.
FAKE_REGION_ID = 999014
AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}
TEMPLATES = Path(settings.BASE_DIR) / 'dashboard' / 'templates' / 'grm'
# Valeur réelle d'un compte AC dans la base : URL S3 d'une image factice, tronquée à 100 caractères.
BROKEN_S3_PHOTO = 'https://cddfiles.s3.amazonaws.com/https%3A/via.placeholder.com/150?AWSAccessKeyId=AKIAVNBI2LQUFQ6X2V'


@pytest.fixture(autouse=True)
def isolate_external_calls(monkeypatch):
    real_get = query_module.QuerySet.get

    def _fake_get(self, *args, **kwargs):
        if self.model is AdministrativeLevel:
            pk = kwargs.get('pk', kwargs.get('id'))
            if pk is not None and int(pk) == FAKE_REGION_ID:
                return AdministrativeLevel(id=FAKE_REGION_ID, name='Village Test', type='Village')
            raise AdministrativeLevel.DoesNotExist()
        return real_get(self, *args, **kwargs)

    monkeypatch.setattr(query_module.QuerySet, 'get', _fake_get)
    from dashboard.grm import views
    for name in ('escalate_issues', 'send_a_new_issue_notification', 'send_issue_status_notifications'):
        monkeypatch.setattr(views, name, lambda: None)


def _assigned_issue(django_user_model, number, photo=''):
    assignee = django_user_model.objects.create_user(
        username=f'ac{number}', email=f'ac{number}@example.com', password='pass1234', first_name='Ama',
    )
    if photo:
        User.objects.filter(pk=assignee.pk).update(photo=photo)
        assignee.refresh_from_db()
    now = timezone.now()
    issue = Issue.objects.create(
        internal_code=f'DRP-FIX-{uuid.uuid4().hex[:8]}', auto_increment_id=number, description='Forage en panne',
        confirmed=True, source='web', publish=True, notification_send=True,
        created_date=now, intake_date=now, issue_date=now,
        status=IssueStatus.objects.create(name='Enregistrée', initial_status=True),
        category=IssueCategory.objects.create(name='Infrastructures'),
        issue_type=IssueType.objects.create(name='Plainte'),
        administrative_region=AdministrativeLevel(id=FAKE_REGION_ID, name='Village Test', type='Village'),
        administrative_region_name='Village Test',
        assignee=assignee, assignee_name=assignee.name,
    )
    return assignee, issue


# ---- Pièce jointe depuis le détail, dans une session sans assistant d'enregistrement ----

@pytest.mark.django_db
def test_upload_attachment_without_session_password(client, django_user_model):
    assignee, issue = _assigned_issue(django_user_model, 301)
    client.force_login(assignee)

    response = client.post(
        reverse('dashboard:grm:upload_issue_attachment', kwargs={'issue': issue.auto_increment_id}),
        {'file': SimpleUploadedFile('preuve.txt', b'constat', content_type='text/plain')}, **AJAX,
    )

    assert response.status_code == 200
    assert Attachment.objects.filter(issue=issue, is_deleted=False).count() == 1


@pytest.mark.django_db
def test_decrypt_attachment_without_session_password_is_404(client, django_user_model):
    assignee, issue = _assigned_issue(django_user_model, 302)
    client.force_login(assignee)

    response = client.get(reverse('dashboard:grm:decrypt_issue_attachment', kwargs={
        'issue': issue.auto_increment_id, 'attachment': str(uuid.uuid4()),
    }))

    assert response.status_code == 404


# ---- Corbeille : confirmation avant suppression ----

@pytest.mark.django_db(databases=['default', 'mis'])
def test_issue_detail_asks_confirmation_before_deleting_attachment(client, django_user_model):
    AdministrativeLevel.objects.using('mis').get_or_create(id=FAKE_REGION_ID, defaults={'name': 'Village Test', 'type': 'Village'})
    assignee, issue = _assigned_issue(django_user_model, 303)
    client.force_login(assignee)
    with translation.override('fr'):
        url = reverse('dashboard:grm:issue_detail', kwargs={'issue': issue.auto_increment_id})

    html = client.get(url).content.decode()

    rendered = re.findall(r'if \(!confirm\(.*?\)\)', html)
    # `escapejs` code le trait d'union (-), affiché « - » par le navigateur.
    assert rendered == ['if (!confirm("Voulez\\u002Dvous vraiment supprimer cette pièce jointe ?"))'], rendered


@pytest.mark.parametrize('template', ['issue_detail.html', 'new_issue_confirm.html', 'new_issue_details.html'])
def test_every_delete_attachment_handler_asks_confirmation(template):
    source = (TEMPLATES / template).read_text(encoding='utf-8')
    source = re.sub(r'{% comment %}.*?{% endcomment %}', '', source, flags=re.S)
    handlers = [m.start() for m in re.finditer(r"on\('click', '\.delete-attachment'", source)]

    assert handlers
    for start in handlers:
        body = source[start:source.index('$.ajax', start)]
        assert 'confirm(' in body, template


# ---- Photo du compte ----

@pytest.mark.parametrize('stored, expected', [
    ('', ''),
    ('https://via.placeholder.com/150', ''),
    (BROKEN_S3_PHOTO, ''),
    ('https://example.org/photos/ama.jpg', 'https://example.org/photos/ama.jpg'),
    ('photos/ama.jpg', None),  # fichier envoyé : URL du stockage
])
def test_photo_url(stored, expected):
    if expected is None:
        expected = default_storage.url(stored)
    assert User(email='ama@example.com', photo=stored).photo_url == expected


@pytest.mark.django_db(databases=['default', 'mis'])
def test_navbar_shows_default_avatar_for_broken_legacy_photo(client, django_user_model):
    AdministrativeLevel.objects.using('mis').get_or_create(id=FAKE_REGION_ID, defaults={'name': 'Village Test', 'type': 'Village'})
    assignee, issue = _assigned_issue(django_user_model, 304, photo=BROKEN_S3_PHOTO)
    client.force_login(assignee)

    html = client.get(reverse('dashboard:grm:issue_detail', kwargs={'issue': issue.auto_increment_id})).content.decode()

    assert 'placeholder.com' not in html
    assert html.count('images/default-avatar.jpg') >= 2  # navbar + barre latérale


# ---- Page Profil : langue de la page, pas celle du navigateur ----

class _FakeSession:
    calls = []

    class cookies:
        @staticmethod
        def get_dict():
            return {}

    def get(self, url, *args, **kwargs):
        return type('R', (), {'status_code': 200, 'json': staticmethod(lambda: {'csrfToken': 'jeton'})})()

    def post(self, url, *args, **kwargs):
        _FakeSession.calls.append((url, kwargs.get('data') or {}))
        return type('R', (), {'text': '<html>profil</html>'})()


@pytest.mark.django_db
@pytest.mark.parametrize('posted, expected', [('fr', 'fr'), ('xx', 'en'), (None, 'en')])
def test_profile_uses_language_of_the_page(client, django_user_model, monkeypatch, posted, expected):
    monkeypatch.setattr('grm.views.requests.Session', _FakeSession)
    _FakeSession.calls = []
    user = django_user_model.objects.create_user(username='profil', email='profil@example.com', password='pass1234')
    client.force_login(user)

    data = {'language': posted} if posted else {}
    response = client.post('/profile/', data, HTTP_ACCEPT_LANGUAGE='en')

    assert response.status_code == 200
    url, sent = _FakeSession.calls[0]
    assert url == f'{settings.CDD_URL_BASE}/{expected}/user-manager/'
    assert sent['language'] == expected


@pytest.mark.django_db(databases=['default', 'mis'])
def test_sidebar_profile_form_sends_page_language(client, django_user_model):
    AdministrativeLevel.objects.using('mis').get_or_create(id=FAKE_REGION_ID, defaults={'name': 'Village Test', 'type': 'Village'})
    assignee, issue = _assigned_issue(django_user_model, 305)
    client.force_login(assignee)
    with translation.override('fr'):
        url = reverse('dashboard:grm:issue_detail', kwargs={'issue': issue.auto_increment_id})

    html = client.get(url, HTTP_ACCEPT_LANGUAGE='en').content.decode()

    assert '<input type="hidden" name="language" value="fr">' in html
