"""Listes de destinataires des notifications email, gérées dans l'admin Django
(issue.models.NotificationRecipient) : lecture, reprise des anciennes listes après confirmation
(migration et commande), accès à l'admin."""
import importlib
from io import StringIO

import pytest
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.urls import reverse

from issue import notification_recipients
from issue.models import NotificationRecipient as R
from issue.notification_recipients import LEGACY_RECIPIENTS, import_legacy_recipients, recipient_emails

pytestmark = pytest.mark.django_db

LEGACY_ACTIVE = sum(1 for *_rest, active in LEGACY_RECIPIENTS if active)
LEGACY_INACTIVE = len(LEGACY_RECIPIENTS) - LEGACY_ACTIVE


def test_recipient_emails_returns_active_addresses_of_the_requested_lists():
    R.objects.create(email=' Kegbaof@Gmail.com ', group=R.GROUP_SAFEGUARD_SPECIALISTS)
    R.objects.create(email='old@example.org', group=R.GROUP_SAFEGUARD_SPECIALISTS, is_active=False)
    R.objects.create(email='sig@example.org', group=R.GROUP_OTHERS)
    R.objects.create(email='sig@example.org', group=R.GROUP_COORDINATORS)

    assert recipient_emails(R.GROUP_SAFEGUARD_SPECIALISTS) == ['kegbaof@gmail.com']
    assert recipient_emails(R.GROUP_OTHERS, R.GROUP_COORDINATORS) == ['sig@example.org']
    assert recipient_emails(R.GROUP_ANADEB) == []


def test_legacy_import_keeps_commented_addresses_inactive_and_is_idempotent():
    assert import_legacy_recipients() == (len(LEGACY_RECIPIENTS), 0)
    assert R.objects.filter(is_active=True).count() == LEGACY_ACTIVE
    inactive = set(R.objects.filter(is_active=False).values_list('email', flat=True))
    assert inactive == {
        'yiroko777@gmail.com', 'adaboubvincent@gmail.com', 'badassan13@gmail.com', 'estherdjallo@gmail.com',
        'moukeram@yahoo.fr',
    }
    assert R.objects.get(email='palerbo@gmail.com').role == 'Evaluator'

    # Réglage fait ensuite dans l'admin : un nouvel import ne l'écrase pas.
    R.objects.filter(email='kegbaof@gmail.com').update(is_active=False)
    assert import_legacy_recipients() == (0, len(LEGACY_RECIPIENTS))
    assert R.objects.get(email='kegbaof@gmail.com').is_active is False


@pytest.mark.parametrize('answer, expected_count', [('no', 0), ('yes', len(LEGACY_RECIPIENTS)), ('oui', len(LEGACY_RECIPIENTS))])
def test_command_asks_for_confirmation(monkeypatch, answer, expected_count):
    monkeypatch.setattr('builtins.input', lambda question: answer)

    call_command('import_notification_recipients', stdout=StringIO())

    assert R.objects.count() == expected_count


def test_command_without_possible_answer_imports_nothing(monkeypatch):
    def no_input(question):
        raise EOFError

    monkeypatch.setattr('builtins.input', no_input)

    call_command('import_notification_recipients', stdout=StringIO())

    assert R.objects.count() == 0


def test_command_yes_and_dry_run_options(monkeypatch):
    monkeypatch.setattr('builtins.input', lambda question: pytest.fail('aucune question attendue'))

    call_command('import_notification_recipients', '--dry-run', stdout=StringIO())
    assert R.objects.count() == 0

    call_command('import_notification_recipients', '--yes', stdout=StringIO())
    assert R.objects.count() == len(LEGACY_RECIPIENTS)


def _migration_function():
    module = importlib.import_module('issue.migrations.0016_import_notification_recipients')
    return module.import_after_confirmation


class _Apps:
    @staticmethod
    def get_model(app_label, model_name):
        return R


def test_migration_imports_nothing_when_nobody_can_answer(monkeypatch):
    """Cas d'un déploiement Elastic Beanstalk (`migrate --noinput`) et des tests."""
    monkeypatch.setattr(notification_recipients, 'is_interactive', lambda: False)
    monkeypatch.setattr('builtins.input', lambda question: pytest.fail('aucune question attendue'))

    _migration_function()(_Apps(), None)

    assert R.objects.count() == 0


@pytest.mark.parametrize('answer, expected_count', [('no', 0), ('yes', len(LEGACY_RECIPIENTS))])
def test_migration_asks_yes_no_before_importing(monkeypatch, answer, expected_count):
    monkeypatch.setattr(notification_recipients, 'is_interactive', lambda: True)
    questions = []
    monkeypatch.setattr('builtins.input', lambda question: questions.append(question) or answer)

    _migration_function()(_Apps(), None)

    assert len(questions) == 1 and '[yes/no]' in questions[0]
    assert R.objects.count() == expected_count


def test_admin_access_needs_the_explicit_permission(client, django_user_model):
    url = reverse('admin:issue_notificationrecipient_changelist')
    superuser = django_user_model.objects.create_superuser(username='root', email='root@example.com', password='x')
    admin_group_member = django_user_model.objects.create_user(
        username='staffadmin', email='staffadmin@example.com', password='x', is_staff=True,
    )
    admin_group_member.groups.add(Group.objects.get_or_create(name='Admin')[0])

    client.force_login(superuser)
    assert client.get(url).status_code == 200

    # Le groupe « Admin » n'a volontairement pas accès à cet écran.
    client.force_login(admin_group_member)
    assert client.get(url).status_code == 403
