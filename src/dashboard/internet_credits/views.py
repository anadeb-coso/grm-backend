"""Espace web « Forfaits internet CVGP » : enregistrement du forfait mensuel (qui déclenche les
notifications mobiles), suivi des confirmations CVGP et FC/AC, exports PDF/Excel.

Accès : superuser, groupe `Admin`, ou groupe dédié `InternetCreditManager`
(internet_credits/permissions.py)."""
import base64

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Prefetch
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils.translation import gettext as _t
from django.utils.translation import gettext_lazy as _
from django.views import generic

from dashboard.mixins import PageMixin
from internet_credits import exports, services
from internet_credits.models import (
    InternetCreditBeneficiary, InternetCreditCampaign, InternetCreditConfirmation,
)
from internet_credits.permissions import InternetCreditManagerRequiredMixin

from .forms import CampaignForm, ExportOptionsForm

LIST_TITLE = _('CVGP internet packages')

STATUS_FILTERS = [
    ('', _('All')),
    ('cvgp_pending', _('CVGP not confirmed')),
    ('cvgp_confirmed', _('CVGP confirmed')),
    ('fc_pending', _('FC/AC not confirmed')),
    ('complete', _('Fully confirmed')),
]


def _breadcrumb(*items):
    crumbs = [{'url': reverse_lazy('dashboard:internet_credits:list'), 'title': LIST_TITLE}]
    crumbs += [{'url': None, 'title': title} for title in items]
    return crumbs


def _active_campaigns():
    return InternetCreditCampaign.objects.filter(is_deleted=False)


def _campaign_or_404(pk):
    return get_object_or_404(_active_campaigns(), pk=pk)


def _flash(request, level, message):
    tag = {messages.SUCCESS: 'success', messages.WARNING: 'warning', messages.ERROR: 'danger'}[level]
    messages.add_message(request, level, message, extra_tags=tag)


def _flash_generation(request, stats):
    _flash(request, messages.SUCCESS, _t(
        '%(created)d CVD line(s) created, %(refreshed)d updated, %(removed)d removed.'
    ) % stats)
    if stats['warnings']:
        _flash(request, messages.WARNING, _t('To check:') + '<br/>' + '<br/>'.join(stats['warnings']))


class ManagerPageMixin(InternetCreditManagerRequiredMixin, LoginRequiredMixin, PageMixin):
    active_level1 = 'internet_credits'


class CampaignListView(ManagerPageMixin, generic.TemplateView):
    template_name = 'internet_credits/list.html'
    title = LIST_TITLE

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        rows = []
        campaigns = _active_campaigns().prefetch_related(Prefetch(
            'beneficiaries',
            queryset=InternetCreditBeneficiary.objects.filter(is_deleted=False)
            .prefetch_related(services.active_confirmations_prefetch()),
            to_attr='active_beneficiaries',
        ))
        for campaign in campaigns:
            lines = [{
                'cvgp': services.cvgp_confirmation(b),
                'fcs': services.fc_confirmations(b),
            } for b in campaign.active_beneficiaries]
            for line in lines:
                line['complete'] = bool(line['cvgp'] and line['fcs'])
            rows.append({'campaign': campaign, 'stats': services.campaign_stats(lines)})
        context['rows'] = rows
        context['breadcrumb'] = _breadcrumb()
        return context


class CampaignCreateView(ManagerPageMixin, generic.CreateView):
    template_name = 'internet_credits/form.html'
    form_class = CampaignForm
    title = _('Register a monthly package')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['breadcrumb'] = _breadcrumb(self.title)
        return context

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        campaign = form.save()
        _flash_generation(self.request, services.sync_campaign_beneficiaries(campaign))
        return redirect('dashboard:internet_credits:detail', pk=campaign.pk)


class CampaignUpdateView(ManagerPageMixin, generic.UpdateView):
    template_name = 'internet_credits/form.html'
    form_class = CampaignForm
    title = _('Edit the monthly package')

    def get_object(self, queryset=None):
        return _campaign_or_404(self.kwargs['pk'])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['breadcrumb'] = _breadcrumb(self.object.month_label, self.title)
        return context

    def form_valid(self, form):
        campaign = form.save()
        services.refresh_campaign_messages(campaign)
        _flash(self.request, messages.SUCCESS, _t(
            'Package updated. Messages of lines not yet confirmed have been updated; '
            'confirmations already signed keep the text that was checked.'
        ))
        return redirect('dashboard:internet_credits:detail', pk=campaign.pk)


class CampaignDetailView(ManagerPageMixin, generic.TemplateView):
    template_name = 'internet_credits/detail.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        campaign = _campaign_or_404(self.kwargs['pk'])
        lines = services.campaign_lines(campaign)
        status = self.request.GET.get('status', '')
        filters = {
            'cvgp_pending': lambda line: not line['cvgp'],
            'cvgp_confirmed': lambda line: line['cvgp'],
            'fc_pending': lambda line: not line['fcs'],
            'complete': lambda line: line['complete'],
        }
        context.update({
            'title': campaign.month_label,
            'campaign': campaign,
            'lines': [line for line in lines if filters[status](line)] if status in filters else lines,
            'stats': services.campaign_stats(lines),
            'warnings': [line['beneficiary'] for line in lines if line['beneficiary'].resolution_warning],
            'status': status,
            'status_filters': STATUS_FILTERS,
            'monthly_export_form': ExportOptionsForm(initial={
                'text': campaign.attestation_text,
                'signatory_name': campaign.signatory_name,
                'signatory_title': campaign.signatory_title,
            }, prefix='monthly'),
            'cvd_export_form': ExportOptionsForm(initial={
                'text': campaign.agreement_text,
                'signatory_name': campaign.signatory_name,
                'signatory_title': campaign.signatory_title,
            }, prefix='cvd'),
            'breadcrumb': _breadcrumb(campaign.month_label),
        })
        return context


class CampaignDeleteView(ManagerPageMixin, generic.View):
    """Suppression logique, autorisée même après confirmation : les notifications disparaissent
    des mobiles au pull suivant."""

    def post(self, request, pk):
        campaign = _campaign_or_404(pk)
        services.soft_delete_campaign(campaign)
        _flash(request, messages.SUCCESS, _t('The package of %(month)s has been deleted.') % {'month': campaign.month_label})
        return redirect('dashboard:internet_credits:list')


class CampaignRefreshView(ManagerPageMixin, generic.View):
    """Ajoute les nouveaux membres CVGP et met à jour les lignes non confirmées."""

    def post(self, request, pk):
        campaign = _campaign_or_404(pk)
        _flash_generation(request, services.sync_campaign_beneficiaries(campaign))
        return redirect('dashboard:internet_credits:detail', pk=campaign.pk)


class ConfirmationResetView(ManagerPageMixin, generic.View):
    def post(self, request, pk):
        confirmation = get_object_or_404(
            InternetCreditConfirmation.objects.select_related('beneficiary__campaign'),
            pk=pk, is_deleted=False, beneficiary__campaign__is_deleted=False,
        )
        services.reset_confirmation(confirmation)
        _flash(request, messages.SUCCESS, _t(
            'The confirmation of %(name)s has been reset: the notification will reappear on the mobile.'
        ) % {'name': confirmation.confirmed_by_name})
        return redirect('dashboard:internet_credits:detail', pk=confirmation.beneficiary.campaign_id)


class ConfirmationSignatureView(ManagerPageMixin, generic.View):
    """Sert l'image de signature (stockée en data URL) : évite d'embarquer toutes les images
    en base64 dans la page de détail."""

    def get(self, request, pk):
        confirmation = get_object_or_404(InternetCreditConfirmation, pk=pk)
        header, _sep, data = (confirmation.signature or '').partition(',')
        if not data or not header.startswith('data:image/'):
            raise Http404
        content_type = header[len('data:'):].split(';')[0]
        response = HttpResponse(base64.b64decode(data), content_type=content_type)
        response['Cache-Control'] = 'private, max-age=3600'
        return response


def _file_response(content, content_type, filename):
    response = HttpResponse(content, content_type=content_type)
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def _slug(text):
    return ''.join(c if c.isalnum() else '_' for c in text).strip('_') or 'cvd'


class _PdfExportView(ManagerPageMixin, generic.View):
    prefix = None
    text_field = None  # champ de la campagne mémorisant le texte personnalisé

    def get_options(self, campaign):
        form = ExportOptionsForm(self.request.POST, prefix=self.prefix)
        if not form.is_valid():
            errors = '; '.join(e for errs in form.errors.values() for e in errs)
            _flash(self.request, messages.ERROR, _t('Export impossible: %(errors)s') % {'errors': errors})
            return None
        options = form.cleaned_data
        if options.get('remember'):
            fields = ['signatory_name', 'signatory_title', 'updated_at']
            campaign.signatory_name = options['signatory_name']
            campaign.signatory_title = options['signatory_title']
            if options.get('text'):
                setattr(campaign, self.text_field, options['text'])
                fields.append(self.text_field)
            campaign.save(update_fields=fields)
        return options


class MonthlyPdfExportView(_PdfExportView):
    prefix = 'monthly'
    text_field = 'attestation_text'

    def post(self, request, pk):
        campaign = _campaign_or_404(pk)
        options = self.get_options(campaign)
        if options is None:
            return redirect('dashboard:internet_credits:detail', pk=campaign.pk)
        pdf = exports.monthly_pdf(campaign, options)
        return _file_response(pdf, 'application/pdf', f'forfait_internet_cvgp_{campaign.period:%Y-%m}.pdf')


class CvdPdfExportView(_PdfExportView):
    prefix = 'cvd'
    text_field = 'agreement_text'

    def post(self, request, pk):
        beneficiary = get_object_or_404(
            InternetCreditBeneficiary.objects.select_related('campaign'),
            pk=pk, is_deleted=False, campaign__is_deleted=False,
        )
        options = self.get_options(beneficiary.campaign)
        if options is None:
            return redirect('dashboard:internet_credits:detail', pk=beneficiary.campaign_id)
        pdf = exports.cvd_pdf(beneficiary, options)
        filename = f'forfait_internet_{beneficiary.campaign.period:%Y-%m}_{_slug(beneficiary.label)}.pdf'
        return _file_response(pdf, 'application/pdf', filename)


class MonthlyExcelExportView(ManagerPageMixin, generic.View):
    def get(self, request, pk):
        campaign = _campaign_or_404(pk)
        return _file_response(
            exports.monthly_excel(campaign),
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            f'forfait_internet_cvgp_{campaign.period:%Y-%m}.xlsx',
        )
