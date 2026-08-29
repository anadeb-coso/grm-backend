import csv

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.urls import reverse, reverse_lazy
from django.utils.html import escape, format_html
from django.utils.translation import gettext, gettext_lazy as _
from django.views import generic
from django.forms import Form

from dashboard.templatetags.custom_tags import adl_names

from authentication.models import User, GovernmentWorker
from authentication.utils import get_validation_code
from authentication.functions import send_code_by_mail
from dashboard.adls.forms import AdlProfileForm, PasswordConfirmForm, GovernmentWorkerAdlProfileForm, CreateAdlProfileForm
from dashboard.adls.serializers import adl_to_legacy_dict
from dashboard.mixins import AJAXRequestMixin, JSONResponseMixin, ModalFormMixin, PageMixin
from authentication.permissions import SpecificPermissionRequiredMixin, AdminPermissionRequiredMixin
from administrativelevels.models import AdministrativeLevel
from grm.call_objects_from_other_db import mis_objects_call
from issue.models import Adl


class AdlListView(SpecificPermissionRequiredMixin, PageMixin, LoginRequiredMixin, generic.ListView):
    template_name = 'adls/list.html'
    context_object_name = 'adls'
    title = _('Administrative Levels')
    active_level1 = 'adls'
    breadcrumb = [
        {
            'url': '',
            'title': title
        },
    ]

    def get_queryset(self):
        # Le tableau est paginé côté serveur (DataTables serverSide -> AdlListDatatableJsonView) :
        # on ne matérialise plus toute la liste des `adl_to_legacy_dict` ici.
        return Adl.objects.none()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['government_worker_form'] = CreateAdlProfileForm()
        return context


class AdlListDatatableJsonView(SpecificPermissionRequiredMixin, LoginRequiredMixin, generic.View):
    """Pagination CÔTÉ SERVEUR de la liste `/administrative-levels/` (protocole DataTables
    `serverSide`), même logique que `dashboard.grm.views.IssueListDatatableJsonView` : le
    navigateur demande une page (`start`/`length`, 10 lignes par défaut), la vue slice
    `Adl.objects` en base et ne renvoie que ces ~10 lignes sérialisées. `?export=csv` renvoie
    en revanche la liste complète (bouton « Exporter la liste complète »).

    Pas de `AJAXRequestMixin` ici (contrairement à `IssueListDatatableJsonView`) : l'export CSV
    se fait par navigation directe (`window.location`), donc sans en-tête `X-Requested-With`.
    L'accès reste protégé par l'authentification + la permission de groupe."""

    ORDER_FIELDS = {
        0: 'name',
        1: None,   # Location Name (résolu via la base `mis`, cross-DB)
        2: None,   # Photo
        3: 'representative_name',
        4: None,   # Action
    }

    def _base_queryset(self):
        return Adl.objects.select_related('representative').all()

    def _apply_search(self, queryset, value):
        value = (value or '').strip()
        if not value:
            return queryset
        return queryset.filter(
            Q(name__icontains=value)
            | Q(representative_name__icontains=value)
            | Q(representative__email__icontains=value)
        )

    def get(self, request, *args, **kwargs):
        if request.GET.get('export') == 'csv':
            return self._export_csv(request)

        def _int(name, default):
            try:
                return int(request.GET.get(name) or default)
            except (TypeError, ValueError):
                return default

        draw = _int('draw', 1)
        start = max(_int('start', 0), 0)
        length = _int('length', 10)

        queryset = self._base_queryset()
        records_total = queryset.count()
        queryset = self._apply_search(queryset, request.GET.get('search[value]'))
        records_filtered = queryset.count()

        order_col = request.GET.get('order[0][column]')
        order_dir = request.GET.get('order[0][dir]') or 'asc'
        order_field = self.ORDER_FIELDS.get(int(order_col)) if (order_col or '').isdigit() else None
        if order_field:
            queryset = queryset.order_by(('-' if order_dir == 'desc' else '') + order_field)
        else:
            queryset = queryset.order_by('-representative_name')

        page = queryset[start:] if length == -1 else queryset[start:start + length]
        data = [self._serialize_row(adl) for adl in page]

        return JsonResponse({
            'draw': draw,
            'recordsTotal': records_total,
            'recordsFiltered': records_filtered,
            'data': data,
        })

    @staticmethod
    def _serialize_row(adl):
        doc = adl_to_legacy_dict(adl)
        rep = doc.get('representative') or {}
        detail_url = reverse('dashboard:adls:detail', args=[doc['_id']])
        photo = rep.get('photo') or static('images/default-avatar.jpg')
        is_active = bool(rep.get('is_active'))
        status_html = format_html(
            '<span class="adl-dot {}" title="{}"></span>',
            'is-on' if is_active else 'is-off',
            gettext('Active') if is_active else gettext('Inactive'),
        )
        return {
            'DT_RowAttr': {'data-href': detail_url},
            '0': format_html('<span class="adl-level">{}</span>', doc.get('name') or '-'),
            '1': format_html('<span class="adl-loc">{}</span>', adl_names(doc)),
            '2': format_html('<img src="{}" class="adl-avatar" alt=""/>', photo),
            '3': format_html('{}<span class="adl-name">{}</span>', status_html, rep.get('name') or '—'),
            '4': format_html(
                '<a href="{}" class="btn-see-profile"><i class="fas fa-arrow-right"></i> {}</a>',
                detail_url, gettext('See profile'),
            ),
        }

    def _export_csv(self, request):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="administrative_levels.csv"'
        writer = csv.writer(response)
        writer.writerow([
            gettext('Administrative Level'), gettext('Location Name'),
            gettext('Name'), gettext('Email'),
        ])
        queryset = self._apply_search(self._base_queryset(), request.GET.get('search[value]'))
        for adl in queryset.order_by('-representative_name'):
            doc = adl_to_legacy_dict(adl)
            rep = doc.get('representative') or {}
            writer.writerow([doc.get('name') or '', adl_names(doc), rep.get('name') or '', rep.get('email') or ''])
        return response


class ADLMixin(SpecificPermissionRequiredMixin, object):
    doc = None
    adl = None

    def dispatch(self, request, *args, **kwargs):
        try:
            self.adl = Adl.objects.select_related('representative').get(pk=kwargs['id'])
        except (Adl.DoesNotExist, ValueError, Exception):
            raise Http404
        self.doc = adl_to_legacy_dict(self.adl)
        return super().dispatch(request, *args, **kwargs)


class AdlDetailView(ADLMixin, PageMixin, LoginRequiredMixin, generic.DetailView):
    template_name = 'adls/profile.html'
    context_object_name = 'adl'
    title = _('Facilitator Profile')
    active_level1 = 'adls'
    breadcrumb = [
        {
            'url': reverse_lazy('dashboard:adls:list'),
            'title': _('Administrative Levels')
        },
        {
            'url': '',
            'title': title
        }
    ]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['password_confirm_form'] = PasswordConfirmForm()
        context['government_worker_form'] = GovernmentWorkerAdlProfileForm(
            initial={'doc_id': self.doc['_id']}
        )
        return context

    def get_object(self, queryset=None):
        return self.doc


class ToggleAdlStatusView(SpecificPermissionRequiredMixin, LoginRequiredMixin, generic.View):

    def post(self, request, *args, **kwargs):
        doc_id = kwargs['id']
        try:
            adl = Adl.objects.select_related('representative').get(pk=doc_id)
            representative = adl.representative
            if representative is None:
                raise Http404

            if representative.is_active:
                form = PasswordConfirmForm(request.POST)
                if not form.is_valid():
                    raise PermissionDenied()

                current_user = request.user
                password = form.cleaned_data['password']
                if not current_user.check_password(password):
                    raise PermissionDenied()

                representative.is_active = False
                representative.save(update_fields=['is_active'])
                msg = _("The account was successfully deactivated.")
                messages.add_message(request, messages.SUCCESS, msg, extra_tags='success')
            else:
                representative.is_active = True
                representative.save(update_fields=['is_active'])
                msg = _("The account was activated successfully.")
                messages.add_message(request, messages.SUCCESS, msg, extra_tags='success')

        except PermissionDenied:
            msg = _("The password was not correct, we could not proceed with action.")
            messages.add_message(request, messages.ERROR, msg, extra_tags='danger')
        except Adl.DoesNotExist:
            raise Http404

        return HttpResponseRedirect(reverse('dashboard:adls:detail', args=[doc_id]))


class CreateAdlGovernmentWorkerProfileFormView(LoginRequiredMixin, generic.View):

    def _administrative_ids(self, ids, _id=None):
        if not ids:
            ids = []
        if _id and _id not in ids:
            ids.append(_id)

        """Search all villages with same cvd"""
        all_adl_on_cvd = []
        for _id in ids:
            _obj = mis_objects_call.filter_objects(AdministrativeLevel, id=int(_id)).first()
            if _obj and _obj.cvd:
                for _village in _obj.cvd.get_villages():
                    if str(_village.id) not in all_adl_on_cvd:
                        all_adl_on_cvd.append(str(_village.id))
            else:
                all_adl_on_cvd.append(_id)

        return list(set(all_adl_on_cvd))

    def post(self, request, *args, **kwargs):
        try:

            form = CreateAdlProfileForm(request.POST)
            if not form.is_valid():
                raise PermissionDenied()

            data = form.cleaned_data
            email = data['email']
            first_name = data['first_name']
            last_name = data['last_name']
            phone = data['phone']

            if not User.objects.filter(email=email).exists():
                user = User()
                user.email = email
                user.first_name = first_name
                user.last_name = last_name
                user.phone_number = phone

                user.save()

                user = User.objects.get(email=email)

                if hasattr(user, 'governmentworker'):
                    governmentworker = GovernmentWorker.objects.get(id=user.governmentworker.id)
                else:
                    governmentworker = GovernmentWorker()
                    governmentworker.user = user
                    governmentworker.department = 1

                governmentworker.administrative_id = data['administrative_level']

                if data['administrative_level'] != "1":
                    governmentworker.administrative_ids = self._administrative_ids(data['administrative_levels'], data['administrative_level'])
                    governmentworker.additional_administrative_ids = self._administrative_ids(data['additional_administrative_ids'])
                else:
                    governmentworker.administrative_ids = list()
                    governmentworker.additional_administrative_ids = list()

                governmentworker.save()

                msg = _("The account has been successfully created.")
                messages.add_message(request, messages.SUCCESS, msg, extra_tags='success')

                # Un nouveau compte "agent" (GovernmentWorker) n'a pas nécessairement de profil
                # `Adl` (facilitateur terrain) associé — contrairement à l'ancien code CouchDB qui
                # supposait toujours l'existence d'un document `adl` correspondant (risque de
                # crash sinon). On redirige vers le profil s'il existe, sinon vers la liste.
                existing_adl = Adl.objects.filter(representative_id=user.id).first()
                if existing_adl:
                    return HttpResponseRedirect(reverse('dashboard:adls:detail', args=[str(existing_adl.pk)]))

            else:
                msg = _("There is already a user with this email address.")
                messages.add_message(request, messages.ERROR, msg, extra_tags='success')

        except PermissionDenied:
            msg = _("An error has occurred...")
            messages.add_message(request, messages.ERROR, msg, extra_tags='danger')

        except Exception as exc:
            messages.add_message(request, messages.ERROR, exc.__str__(), extra_tags='danger')

        return HttpResponseRedirect(reverse('dashboard:adls:list'))


class EditAdlProfileFormView(ADLMixin, AJAXRequestMixin, ModalFormMixin, LoginRequiredMixin, JSONResponseMixin,
                             generic.FormView):
    form_class = AdlProfileForm
    title = _('Profile information')
    picture = static('images/default-avatar.jpg')
    picture_class = "edit-profile-user-img"
    submit_button = _('Save')

    def get_context_data(self, **kwargs):
        picture = self.doc['representative']['photo'] if self.doc.get('representative') else ""
        if picture:
            self.picture = picture
        context = super().get_context_data(**kwargs)
        return context

    def get_form_kwargs(self):
        self.initial = {'doc_id': self.doc['_id']}
        return super().get_form_kwargs()

    def form_valid(self, form):
        data = form.cleaned_data
        user = self.adl.representative
        if user is None:
            raise Http404

        photo_url = user.photo.url if user.photo else ''
        if data['file']:
            user.photo = data['file']
            photo_url = None  # renseigné après save()

        user.first_name = ' '.join(data['name'].split(' ')[:-1]) or data['name']
        user.last_name = data['name'].split(' ')[-1] if ' ' in data['name'] else ''
        user.phone_number = data['phone']

        email = data['email'].lower()
        adl_code = get_validation_code(email)
        if user.email != email:
            msg = _("Please note that the Facilitator Code has changed due to the email change.")
            messages.add_message(self.request, messages.INFO, msg, extra_tags='info')
        user.email = email
        user.save()

        if photo_url is None:
            photo_url = user.photo.url if user.photo else ''

        # `Adl.representative_name` est un cache dénormalisé (utilisé côté sync mobile) — on le
        # garde synchronisé avec le nom réel de l'utilisateur.
        self.adl.representative_name = data['name']
        # `updated_at` explicitement listé : `save(update_fields=...)` n'applique `auto_now` que
        # pour les champs listés — sans lui, ce renommage restait invisible au pull mobile
        # (référentiel `adls`, lecture seule côté mobile).
        self.adl.save(update_fields=['representative_name', 'updated_at'])

        msg = _("The profile information was successfully edited.")
        messages.add_message(self.request, messages.SUCCESS, msg, extra_tags='success')
        context = {
            'msg': render(self.request, 'common/messages.html').content.decode("utf-8"),
            'adl_code': adl_code,
            'photo': photo_url,
        }
        return self.render_to_json_response(context, safe=False)


class EditAdlGovernmentWorkerProfileFormView(SpecificPermissionRequiredMixin, LoginRequiredMixin, generic.View):

    def _administrative_ids(self, ids, _id=None):
        if not ids:
            ids = []
        if _id and _id not in ids:
            ids.append(_id)

        """Search all villages with same cvd"""
        all_adl_on_cvd = []
        for _id in ids:
            _obj = mis_objects_call.filter_objects(AdministrativeLevel, id=int(_id)).first()
            if _obj and _obj.cvd:
                for _village in _obj.cvd.get_villages():
                    if str(_village.id) not in all_adl_on_cvd:
                        all_adl_on_cvd.append(str(_village.id))
            else:
                all_adl_on_cvd.append(_id)

        return list(set(all_adl_on_cvd))

    def post(self, request, *args, **kwargs):
        doc_id = kwargs['id']

        try:
            adl = Adl.objects.select_related('representative').get(pk=doc_id)
            if adl.representative is None:
                raise Http404

            form = GovernmentWorkerAdlProfileForm(
                request.POST, initial={'doc_id': doc_id}
            )
            if not form.is_valid():
                raise PermissionDenied()

            user_obj = adl.representative
            data = form.cleaned_data
            if hasattr(user_obj, 'governmentworker'):
                governmentworker = GovernmentWorker.objects.get(id=user_obj.governmentworker.id)
            else:
                governmentworker = GovernmentWorker()
                governmentworker.user = user_obj
                governmentworker.department = 1

            governmentworker.administrative_id = data['administrative_level']

            governmentworker.administrative_ids = self._administrative_ids(data['administrative_levels'], data['administrative_level'])
            governmentworker.additional_administrative_ids = self._administrative_ids(data['additional_administrative_ids'])

            governmentworker.save()

            msg = _("The profile information was successfully edited.")
            messages.add_message(request, messages.SUCCESS, msg, extra_tags='success')

        except PermissionDenied:
            msg = _("An error has occurred...")
            messages.add_message(request, messages.ERROR, msg, extra_tags='danger')
        except Adl.DoesNotExist:
            raise Http404

        return HttpResponseRedirect(reverse('dashboard:adls:detail', args=[doc_id]))


class SendUserCodeConfirmationView(ADLMixin, AJAXRequestMixin, ModalFormMixin, LoginRequiredMixin,
                                   JSONResponseMixin, generic.FormView):
    form_class = Form
    title = _('Send the confirmation code to this user')
    submit_button = _('Send')
    permissions = ('read',)
    id_form = "send_code_form"

    def post(self, request, *args, **kwargs):
        try:
            email = self.doc['representative']['email']
            send_code_by_mail(
                User.objects.get(email=email),
                get_validation_code(email)
            )  # Send user account code on their Email
            msg = _("Code was successfully sent.")
            messages.add_message(self.request, messages.SUCCESS, msg, extra_tags='success')
        except Exception:
            msg = _("An error occurred during transmission.")
            messages.add_message(self.request, messages.ERROR, msg, extra_tags='error')

        context = {'msg': render(self.request, 'common/messages.html').content.decode("utf-8")}
        return self.render_to_json_response(context, safe=False)
