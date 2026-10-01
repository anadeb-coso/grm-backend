import pytest
from django.template.loader import render_to_string
from django.test import Client
from django.urls import reverse
from django.utils import translation

from internet_credits import services
from internet_credits.models import (
    InternetCreditBeneficiary, InternetCreditCampaign, InternetCreditConfirmation,
)

from .conftest import SIGNATURE, confirmation_record, make_user

pytestmark = pytest.mark.django_db


def url(name, *args):
    return reverse(f'dashboard:internet_credits:{name}', args=args)


@pytest.fixture
def manager(django_user_model):
    user = make_user(django_user_model, 'manager', ['InternetCreditManager'])
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def confirmed(actors, campaign):
    line = InternetCreditBeneficiary.objects.get(campaign=campaign, cvgp_member=actors['cvgp'])
    confirmation, _ = services.create_confirmation(actors['cvgp'], confirmation_record(line), 'grm_mobile')
    return line, confirmation


def test_access_is_restricted(django_user_model, manager):
    assert manager.get(url('list')).status_code == 200
    outsider = Client()
    outsider.force_login(make_user(django_user_model, 'viewer', ['Viewer']))
    assert outsider.get(url('list')).status_code == 404
    admin = Client()
    admin.force_login(make_user(django_user_model, 'admin1', ['Admin']))
    assert admin.get(url('list')).status_code == 200


def test_create_campaign_generates_lines(actors, manager):
    resp = manager.post(url('create'), {
        'period': '2026-10', 'sent_date': '2026-10-02', 'package_label': '3 Go valables 30 jours',
        'amount': 3000, 'cvgp_message_template': 'CVGP du CVD {cvd} — {mois} {annee}',
        'fc_message_template': 'FC : {cvd}', 'attestation_text': 'Attestation', 'agreement_text': 'Accord',
        'signatory_name': '', 'signatory_title': '',
    })
    campaign = InternetCreditCampaign.objects.get(period='2026-10-01')
    assert resp.status_code == 302 and resp['Location'] == url('detail', campaign.pk)
    messages = {b.cvgp_message for b in campaign.beneficiaries.all()}
    assert messages == {'CVGP du CVD KPEKPE — Octobre 2026', 'CVGP du CVD DAPAONG — Octobre 2026'}
    assert campaign.created_by.username == 'manager'


def test_duplicate_month_is_refused(actors, campaign, manager):
    resp = manager.post(url('create'), {
        'period': '2026-09', 'sent_date': '2026-09-05', 'package_label': 'x', 'amount': 1,
        'cvgp_message_template': 'x', 'fc_message_template': 'x', 'attestation_text': 'x', 'agreement_text': 'x',
    })
    assert resp.status_code == 200
    assert InternetCreditCampaign.objects.filter(is_deleted=False).count() == 1


def test_detail_page_and_filters(confirmed, campaign, manager):
    resp = manager.get(url('detail', campaign.pk))
    assert resp.status_code == 200
    assert b'KPEKPE' in resp.content and b'DAPAONG' in resp.content
    with translation.override('fr'):  # tests en anglais (grm/test_settings.py) ; exploitation en français
        french = manager.get(url('detail', campaign.pk))
    assert 'Confirmations par CVD'.encode() in french.content
    pending = manager.get(url('detail', campaign.pk), {'status': 'cvgp_pending'})
    assert b'DAPAONG' in pending.content and b'Kpekpe Centre' not in pending.content


def test_update_campaign_refreshes_unconfirmed_messages(actors, confirmed, campaign, manager):
    resp = manager.post(url('update', campaign.pk), {
        'period': '2026-09', 'sent_date': '2026-09-03', 'package_label': '3 Go', 'amount': 3000,
        'cvgp_message_template': 'Nouveau {cvd}', 'fc_message_template': 'FC {cvd}',
        'attestation_text': 'A', 'agreement_text': 'B', 'signatory_name': 'M. X', 'signatory_title': 'DG',
    })
    assert resp.status_code == 302
    other = InternetCreditBeneficiary.objects.get(campaign=campaign, cvgp_member=actors['cvgp_other'])
    assert other.cvgp_message == 'Nouveau DAPAONG'
    line, confirmation = confirmed
    line.refresh_from_db()
    assert line.cvgp_message.startswith('CVGP du CVD KPEKPE')  # déjà confirmé : figé


def test_exports(confirmed, campaign, manager):
    line, _ = confirmed
    excel = manager.get(url('export_excel', campaign.pk))
    assert excel.status_code == 200 and 'spreadsheetml' in excel['Content-Type']

    pdf = manager.post(url('export_pdf', campaign.pk), {
        'monthly-text': 'Je confirme ({mois} {annee})', 'monthly-signature_mode': 'drawn',
        'monthly-drawn_signature': SIGNATURE, 'monthly-signatory_name': 'M. TINDAME', 'monthly-remember': 'on',
    })
    assert pdf.status_code == 200 and pdf['Content-Type'] == 'application/pdf'
    assert 'forfait_internet_cvgp_2026-09.pdf' in pdf['Content-Disposition']
    campaign.refresh_from_db()
    assert campaign.attestation_text == 'Je confirme ({mois} {annee})' and campaign.signatory_name == 'M. TINDAME'

    cvd = manager.post(url('export_cvd_pdf', line.pk), {'cvd-signature_mode': 'blank', 'cvd-text': ''})
    assert cvd.status_code == 200 and 'KPEKPE' in cvd['Content-Disposition']


def test_pdf_export_with_drawn_mode_but_no_signature_redirects(campaign, manager):
    resp = manager.post(url('export_pdf', campaign.pk), {'monthly-signature_mode': 'drawn', 'monthly-drawn_signature': ''})
    assert resp.status_code == 302 and resp['Location'] == url('detail', campaign.pk)


def test_signature_image_and_reset(confirmed, campaign, manager):
    line, confirmation = confirmed
    image = manager.get(url('signature', confirmation.pk))
    assert image.status_code == 200 and image['Content-Type'] == 'image/png'

    assert manager.post(url('reset_confirmation', confirmation.pk)).status_code == 302
    assert InternetCreditConfirmation.objects.get(pk=confirmation.pk).is_deleted


def test_refresh_and_delete(actors, campaign, manager, django_user_model):
    make_user(django_user_model, 'cvgp3', ['CVGPMembers'], ['301'])
    assert manager.post(url('refresh', campaign.pk)).status_code == 302
    assert campaign.beneficiaries.filter(is_deleted=False).count() == 3

    assert manager.post(url('delete', campaign.pk)).status_code == 302
    campaign.refresh_from_db()
    assert campaign.is_deleted
    assert not campaign.beneficiaries.filter(is_deleted=False).exists()
    assert manager.get(url('detail', campaign.pk)).status_code == 404


def test_sidebar_link_only_for_managers(django_user_model):
    def sidebar(user):
        return render_to_string('layouts/sidebar.html', {'user': user})

    assert url('list') in sidebar(make_user(django_user_model, 'manager2', ['InternetCreditManager']))
    assert url('list') in sidebar(make_user(django_user_model, 'admin2', ['Admin']))
    assert url('list') not in sidebar(make_user(django_user_model, 'viewer2', ['Viewer']))
