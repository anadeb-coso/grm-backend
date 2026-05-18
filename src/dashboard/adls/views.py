from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import render
from django.templatetags.static import static
from django.urls import reverse, reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views import generic
from django.forms import Form

from authentication import ADL
from authentication.models import User, GovernmentWorker
from authentication.utils import get_validation_code
from authentication.functions import send_code_by_mail
from client import COUCHDB_ATTACHMENT_DATABASE, get_db, upload_file
from dashboard.adls.forms import AdlProfileForm, PasswordConfirmForm, GovernmentWorkerAdlProfileForm, CreateAdlProfileForm
from dashboard.mixins import AJAXRequestMixin, JSONResponseMixin, ModalFormMixin, PageMixin
from authentication.permissions import SpecificPermissionRequiredMixin, AdminPermissionRequiredMixin
from administrativelevels.models import AdministrativeLevel
from grm.call_objects_from_other_db import mis_objects_call


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
        eadl_db = get_db()
        return eadl_db.get_query_result({"type": {"$eq": ADL}})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['government_worker_form'] = CreateAdlProfileForm()
        return context


class ADLMixin(SpecificPermissionRequiredMixin, object):
    doc = None

    def dispatch(self, request, *args, **kwargs):
        eadl_db = get_db()
        try:
            self.doc = eadl_db[kwargs['id']]
            if self.doc['type'] != ADL:
                raise Http404
        except Exception:
            raise Http404
        return super().dispatch(request, *args, **kwargs)


class AdlDetailView(ADLMixin, PageMixin, LoginRequiredMixin, generic.DetailView):
    template_name = 'adls/profile.html'
    context_object_name = 'adl'
    title = _('Facilitator Profile')
    active_level1 = 'adls'
    model = User
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
            initial = {'doc_id': self.doc['_id']}
        )
        return context

    def get_object(self, queryset=None):
        return self.doc


class ToggleAdlStatusView(SpecificPermissionRequiredMixin, LoginRequiredMixin, generic.View):

    def post(self, request, *args, **kwargs):
        doc_id = kwargs['id']
        eadl_db = get_db()
        try:
            document = eadl_db[doc_id]
            if document['type'] != ADL:
                raise Http404

            if document['representative']['is_active']:
                form = PasswordConfirmForm(request.POST)
                if not form.is_valid():
                    raise PermissionDenied()

                current_user = request.user
                password = form.cleaned_data['password']
                if not current_user.check_password(password):
                    raise PermissionDenied()

                document['representative']['is_active'] = False
                document.save()
                msg = _("The account was successfully deactivated.")
                messages.add_message(request, messages.SUCCESS, msg, extra_tags='success')
            else:
                document['representative']['is_active'] = True
                document.save()
                msg = _("The account was activated successfully.")
                messages.add_message(request, messages.SUCCESS, msg, extra_tags='success')

        except PermissionDenied:
            msg = _("The password was not correct, we could not proceed with action.")
            messages.add_message(request, messages.ERROR, msg, extra_tags='danger')
        except Exception:
            raise Http404

        return HttpResponseRedirect(reverse('dashboard:adls:detail', args=[doc_id]))


class CreateAdlGovernmentWorkerProfileFormView(LoginRequiredMixin, generic.View):
    
    def _administrative_ids(self, ids, _id=None):
        if not ids:
            ids = []
        if _id and not _id in ids:
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
        eadl_db = get_db()
        
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
                
                return HttpResponseRedirect(reverse('dashboard:adls:detail', args=[
                    eadl_db.get_query_result({"type": "adl", "representative.id": user.id})[0][0]["_id"]
                ]))
            
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
        picture = self.doc["representative"]["photo"] if "photo" in self.doc["representative"] else ""
        if picture:
            self.picture = picture
        context = super().get_context_data(**kwargs)
        return context

    def get_form_kwargs(self):
        self.initial = {'doc_id': self.doc['_id']}
        return super().get_form_kwargs()

    def form_valid(self, form):
        data = form.cleaned_data
        doc = self.doc
        photo = doc["representative"]["photo"] if "photo" in doc["representative"] else ""
        if data['file']:
            response = upload_file(data['file'])
            if response['ok']:
                if photo:
                    attachment_db = get_db(COUCHDB_ATTACHMENT_DATABASE)
                    try:
                        attachment_id = photo.split('/')[2]
                        attachment_db[attachment_id].delete()
                    except Exception:
                        pass
                photo = f'/attachments/{response["id"]}/{data["file"].name}'
                doc["representative"]["photo"] = photo
            else:
                msg = _("An error has occurred that did not allow the profile picture to be uploaded to the database. "
                        "Please report to IT staff.")
                messages.add_message(self.request, messages.ERROR, msg, extra_tags='danger')
        doc['representative']['name'] = data['name']
        doc['representative']['phone'] = data['phone']
        email = data['email'].lower()
        adl_code = get_validation_code(email)
        if doc['representative']['email'] != email:
            msg = _("Please note that the Facilitator Code has changed due to the email change.")
            messages.add_message(self.request, messages.INFO, msg, extra_tags='info')
        doc['representative']['email'] = email
        doc.save()
        
        """Edit User"""
        user = User.objects.filter(id=doc['representative']['id']).first()
        if user:
            user.email = doc['representative']['email']
            user.photo = doc['representative']['photo']
            user.phone_number = doc['representative']['phone']
            
            last_name = doc['representative']['name'].split(' ')[-1]
            first_name = ' '.join(doc['representative']['name'].split(' ')[:-1])
            user.first_name = first_name
            user.last_name = last_name
            
            user.save()

        msg = _("The profile information was successfully edited.")
        messages.add_message(self.request, messages.SUCCESS, msg, extra_tags='success')
        context = {
            'msg': render(self.request, 'common/messages.html').content.decode("utf-8"),
            'adl_code': adl_code,
            'photo': photo,
        }
        return self.render_to_json_response(context, safe=False)



class EditAdlGovernmentWorkerProfileFormView(SpecificPermissionRequiredMixin, LoginRequiredMixin, generic.View):
    
    def _administrative_ids(self, ids, _id=None):
        if not ids:
            ids = []
        if _id and not _id in ids:
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
        eadl_db = get_db()
        
        try:
            user_doc = eadl_db[doc_id]
            if user_doc['type'] != ADL:
                raise Http404

            form = GovernmentWorkerAdlProfileForm(
                request.POST, initial = {'doc_id': doc_id}
            )
            if not form.is_valid():
                raise PermissionDenied()
            
            user_obj = User.objects.get(id=user_doc['representative']['id'])
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
        except Exception:
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
            send_code_by_mail(
                User.objects.get(email=self.doc['representative']['email']), 
                get_validation_code(self.doc['representative']['email'])
            ) # Send user account code on their Email
            msg = _("Code was successfully sent.")
            messages.add_message(self.request, messages.SUCCESS, msg, extra_tags='success')
        except:
            msg = _("An error occurred during transmission.")
            messages.add_message(self.request, messages.ERROR, msg, extra_tags='error')

        
        context = {'msg': render(self.request, 'common/messages.html').content.decode("utf-8")}
        return self.render_to_json_response(context, safe=False)