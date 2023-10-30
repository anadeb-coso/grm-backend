import random
from datetime import datetime, timedelta

# import cryptocode
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse, reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views import generic
from cryptography.fernet import InvalidToken
from django.contrib.auth.hashers import check_password
from django.db.models import Q

from authentication.models import Cdata, GovernmentWorker, Pdata, anonymize_issue_data, get_assignee
from client import get_db, upload_file
from dashboard.adls.forms import PasswordConfirmForm
from dashboard.forms.forms import FileForm
from dashboard.grm import CHOICE_CONTACT
from dashboard.grm.forms import (
    IssueCommentForm, IssueDetailsForm, IssueRejectReasonForm, IssueResearchResultForm, MAX_LENGTH, NewIssueConfirmForm,
    NewIssueContactForm, NewIssueDetailsForm, NewIssueLocationForm, NewIssuePersonForm, SearchIssueForm, 
    IssueOpenStatusForm, IssueReasonCommentForm, IssueIssueEscalateForm, IssueSetUnresolvedForm,
    IssueIssuePublishForm, IssueIssueUnpublishForm, IssueCategoryForm
)
from dashboard.mixins import AJAXRequestMixin, JSONResponseMixin, ModalFormMixin, PageMixin
from grm.utils import (
    get_administrative_level_descendants, get_auto_increment_id, get_child_administrative_regions,
    get_parent_administrative_level, get_administrative_level_descendants_using_mis, 
    get_child_administrative_regions_using_mis, cryptography_fernet_encrypt,
    cryptography_fernet_decrypt, delete_file_on_download_file
)
from dashboard.grm.functions import get_issue_status_stories
from dashboard.tasks import check_issues, send_sms_message, escalate_issues, send_a_new_issue_notification
from authentication.permissions import AdminPermissionRequiredMixin
from privacy.functions import get_last_category_password, get_all_privacy_passwords

COUCHDB_GRM_DATABASE = settings.COUCHDB_GRM_DATABASE
COUCHDB_DATABASE_ADMINISTRATIVE_LEVEL = settings.COUCHDB_DATABASE_ADMINISTRATIVE_LEVEL
COUCHDB_GRM_ATTACHMENT_DATABASE = settings.COUCHDB_GRM_ATTACHMENT_DATABASE



class IssueCommentsContextMixin:
    doc_department = None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        try:
            self.doc_department = self.grm_db.get_query_result({
                "id": self.doc['category']['assigned_department'],
                "type": 'issue_department'
            })[0][0]
            context['colors'] = ['warning', 'mediumslateblue', 'gray', 'mediumpurple', 'plum', 'primary', 'danger']
            comments = self.doc['comments'] if 'comments' in self.doc else list()
            reasons = self.doc['reasons'] if 'reasons' in self.doc else list()
            users = {r['user_id'] for r in reasons} | {c['id'] for c in comments} | {
                (self.doc['assignee']['id'] if type(self.doc['assignee']) == dict else 0), self.doc_department['head']['id']} | {
                    self.request.user.id}
            indexed_users = {}
            for index, user_id in enumerate(users):
                indexed_users[user_id] = index
            context['indexed_users'] = indexed_users
        except Exception:
            pass
        return context


class DashboardTemplateView(PageMixin, LoginRequiredMixin, generic.TemplateView):
    template_name = 'grm/dashboard.html'
    title = _('GRM')
    active_level1 = 'grm'
    breadcrumb = [
        {
            'url': '',
            'title': title
        },
    ]
    
    def dispatch(self, request, *args, **kwargs):
        check_issues()
        escalate_issues()
        send_sms_message()
        send_a_new_issue_notification()
        return super().dispatch(request, *args, **kwargs)


class StartNewIssueView(LoginRequiredMixin, generic.View):

    def post(self, request, *args, **kwargs):
        grm_db = get_db(COUCHDB_GRM_DATABASE)
        auto_increment_id = get_auto_increment_id(grm_db)
        user = request.user
        sample_words = ["Tree", "Cat", "Dog", "Car", "House"]
        issue = {
            "auto_increment_id": auto_increment_id,
            "reporter": {
                "id": user.id,
                "name": user.name
            },
            "assignee": {
                "id": user.id,
                "name": user.name
            },
            "created_date": datetime.now().strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
            "confirmed": False,
            "escalate_flag": False,
            "created_by": False,
            "tracking_code": f'{random.choice(sample_words)}{random.choice(range(1, 1000))}',
            "type": "issue"
        }
        grm_db.create_document(issue)
        return HttpResponseRedirect(
            reverse('dashboard:grm:new_issue_step_1', kwargs={'issue': issue['auto_increment_id']}))


class IssueMixin:
    doc = None
    grm_db = None
    eadl_db = None
    adl_db = None
    max_attachments = 20
    permissions = ('read', 'write')
    has_permission = True

    def get_query_result(self, **kwargs):
        return self.grm_db.get_query_result({
            "auto_increment_id": kwargs['issue'],
            "type": 'issue'
        })

    def check_permissions(self):
        user = self.request.user

        if self.doc["confirmed"]:
            if user.groups.filter(name__in=["Admin", "Assignee"]).exists():
                self.has_permission = True
            elif 'read_only_by_reporter' in self.permissions and self.doc['reporter']['id'] != user.id:
                self.has_permission = False
            else:
                is_assigned = 'assignee' in self.doc and self.doc['assignee']
                if hasattr(user, 'governmentworker') and is_assigned and self.doc['assignee']['id'] != user.id:
                    if 'read' not in self.permissions and \
                            'read_only_by_reporter' not in self.permissions:
                        self.has_permission = False
                    else:
                        if 'read_only_by_reporter' in self.permissions:
                            if self.doc['reporter']['id'] != user.id:
                                self.has_permission = False
                        else:
                            if not user.governmentworker.has_read_permission_for_issue(self.adl_db, self.doc):
                                self.has_permission = False
                            if 'write' not in self.permissions:
                                self.has_permission = False

    def specific_permissions(self):
        user = self.request.user
        if not (
                user.groups.all().exists() 
                or 
                (self.doc.get('reporter') and self.doc.get('reporter').get('id') == user.id)
                or 
                (self.doc.get('assignee') and self.doc.get('assignee').get('id') == user.id) 
                or 
                hasattr(user, 'governmentworker') and user.governmentworker.administrative_id == "1"
            ):
            raise PermissionDenied
        
    def dispatch(self, request, *args, **kwargs):
        self.grm_db = get_db(COUCHDB_GRM_DATABASE)
        self.eadl_db = get_db()
        self.adl_db = get_db(COUCHDB_DATABASE_ADMINISTRATIVE_LEVEL)
        docs = self.get_query_result(**kwargs)
        try:
            self.doc = self.grm_db[docs[0][0]['_id']]
        except Exception:
            raise Http404

        self.check_permissions()
        if not self.has_permission:
            raise PermissionDenied

        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['doc'] = self.doc
        context['max_attachments'] = self.max_attachments
        context['choice_contact'] = CHOICE_CONTACT
        user = self.request.user
        is_assigned = 'assignee' in self.doc and self.doc['assignee']
        permission_to_edit = False
        if user.groups.filter(name="Admin").exists():
            permission_to_edit = True
        elif hasattr(user, 'governmentworker') and self.doc and "administrative_region" in self.doc and "administrative_id" in self.doc["administrative_region"]:
            # parent_id = user.governmentworker.administrative_id
            # descendants = get_administrative_level_descendants_using_mis(None, parent_id, [], self.request.user)
            # allowed_regions = descendants + [parent_id]

            parents_id = user.governmentworker.all_administrative_ids
            descendants = []
            for _id in parents_id:
                descendants += get_administrative_level_descendants_using_mis(None, _id, [], self.request.user)
            allowed_regions = descendants + parents_id

            if self.doc["administrative_region"]["administrative_id"] in allowed_regions:
                permission_to_edit = True
        # elif is_assigned and self.doc['assignee']['id'] == user.id:
        #     permission_to_edit = True
        # elif hasattr(user, 'governmentworker') and is_assigned and self.doc['assignee']['id'] != user.id:
        #     permission_to_edit = False
          

        context['permission_to_edit'] = permission_to_edit
        return context


class UploadIssueAttachmentFormView(IssueMixin, AJAXRequestMixin, ModalFormMixin, LoginRequiredMixin, JSONResponseMixin,
                                    generic.FormView):
    form_class = FileForm
    title = _('Add attachment')
    submit_button = _('Upload')
    permissions = ('read',)

    def form_valid(self, form):
        data = form.cleaned_data
        attachments = self.doc['attachments'] if 'attachments' in self.doc else list()

        reason = self.request.GET.get('reason', '')
        reasons = self.doc['reasons'] if 'reasons' in self.doc else list()

        if len(attachments) < self.max_attachments or reason:
            issue_password_file = data['issue_password_file']
            file = data['file']
            _ok = True
            if  ((self.doc.get('category') and self.doc['category']["id"] in (4, 7)) or not self.doc.get('category')) and issue_password_file:
                last_category_password = get_last_category_password(self.doc['category']["id"])
                if not last_category_password:
                    msg = _("The file has not been saved. No password is defined for this category of complaint.")
                    messages.add_message(self.request, messages.ERROR, msg, extra_tags='error')
                    _ok = False
                elif not check_password(issue_password_file, last_category_password.password):
                    msg = _("The file has not been saved. The password does not match.")
                    messages.add_message(self.request, messages.ERROR, msg, extra_tags='error')
                    _ok = False
                else:
                    file = cryptography_fernet_encrypt(file, issue_password_file,  _type="file", filename=file.name)
                    file.name = f'encrypt_{file.name}' if 'encrypt_' not in file.name else file.name
            
            if _ok:
                response = upload_file(file, COUCHDB_GRM_ATTACHMENT_DATABASE)
                if response['ok']:
                    attachment = {
                        "name": file.name,
                        "url": f'/grm_attachments/{response["id"]}/{file.name}',
                        "local_url": "",
                        "id": datetime.now().strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
                        "uploaded": True,
                        "bd_id": response['id'],
                        "subject": "issue"
                    }
                    
                    if reason:
                        attachment["type"] = "file"
                        attachment["subject"] = "reason"
                        attachment["user_id"] = self.request.user.id
                        attachment["user_name"] = self.request.user.name
                        reasons.insert(0, attachment)
                        self.doc['reasons'] = reasons
                    else:
                        attachments.append(attachment)
                        self.doc['attachments'] = attachments

                    self.doc.save()

                    # delete_file_on_download_file(file) #delete file on server


                    msg = _("The attachment was successfully uploaded.")
                    messages.add_message(self.request, messages.SUCCESS, msg, extra_tags='success')
                else:
                    msg = _("An error has occurred that did not allow the attachment to be uploaded to the database. "
                            "Please report to IT staff.")
                    messages.add_message(self.request, messages.ERROR, msg, extra_tags='danger')
        else:
            msg = _("The file could not be uploaded because it has already reached the limit of %(max)d attachments."
                    ) % {'max': self.max_attachments}
            messages.add_message(self.request, messages.ERROR, msg, extra_tags='danger')
        context = {'msg': render(self.request, 'common/messages.html').content.decode("utf-8")}
        return self.render_to_json_response(context, safe=False)


class IssueAttachmentDeleteView(IssueMixin, AJAXRequestMixin, ModalFormMixin, LoginRequiredMixin, JSONResponseMixin,
                                generic.DeleteView):
    permissions = ('read',)

    def delete(self, request, *args, **kwargs):
        # if 'attachments' in self.doc:
       
        self.specific_permissions()
        
        attachments = self.doc['attachments'] if 'attachments' in self.doc else list()
        grm_attachment_db = get_db(COUCHDB_GRM_ATTACHMENT_DATABASE)
        for attachment in attachments:
            if attachment['id'] == kwargs['attachment']:
                try:
                    grm_attachment_db[attachment['bd_id']].delete()
                except Exception:
                    pass
                attachments.remove(attachment)
                break
        
        reasons = self.doc['reasons'] if 'reasons' in self.doc else list()
        for reason in reasons:
            if (reason.get('due_at') and reason['due_at'] == kwargs['attachment']) or \
                (reason.get('id') and reason['id'] == kwargs['attachment']):
                try:
                    grm_attachment_db[reason['bd_id']].delete()
                except Exception:
                    pass
                reasons.remove(reason)
                break

        try:
            self.doc.save()
        except:
            pass
        msg = _("The attachment was successfully deleted.")
        messages.add_message(self.request, messages.SUCCESS, msg, extra_tags='success')
        context = {'msg': render(self.request, 'common/messages.html').content.decode("utf-8")}
        return self.render_to_json_response(context, safe=False)
        # else:
        #     raise Http404


# class IssueAttachmentDecryptView(IssueMixin, AJAXRequestMixin, ModalFormMixin, LoginRequiredMixin, JSONResponseMixin,
#                                 generic.DeleteView):
class IssueAttachmentDecryptView(IssueMixin, ModalFormMixin, LoginRequiredMixin,
                                generic.DeleteView):

    def get(self, request, *args, **kwargs):
        self.specific_permissions()
        
        password = request.GET.get('password')
        print(password)
        if not password:
            raise Http404
        else:
            category_password = get_last_category_password(self.doc["category"]["id"])
            if not category_password or not (category_password and check_password(password, category_password.password)):
                raise PermissionDenied
        
        attachments = self.doc['attachments'] if 'attachments' in self.doc else list()
        grm_attachment_db = get_db(COUCHDB_GRM_ATTACHMENT_DATABASE)
        attachment_name = None
        _doc = None

        for attachment in attachments:
            if attachment['id'] == kwargs['attachment']:
                try:
                   attachment_name = attachment['name']
                   _doc = grm_attachment_db[attachment['bd_id']]
                except Exception:
                    pass
                break
            
        reasons = self.doc['reasons'] if 'reasons' in self.doc else list()
        for reason in reasons:
            if (reason.get('due_at') and reason['due_at'] == kwargs['attachment']) or \
                (reason.get('id') and reason['id'] == kwargs['attachment']):
                try:
                    attachment_name = reason['name']
                    _doc = grm_attachment_db[reason['bd_id']]
                except Exception:
                    pass
                break
            
        if not attachment_name or not _doc or not _doc.get('_attachments') or not _doc.get('_attachments').get(attachment_name):
            raise Http404
        
        attachment_content = _doc.get_attachment(attachment_name)
        for cat_pass in get_all_privacy_passwords(self.doc["category"]["id"]):
            try:
                return cryptography_fernet_decrypt(attachment_content, cat_pass, _type="file", filename=attachment_name)
            except:
                pass
        
        raise PermissionDenied
        # msg = _("The attachment was successfully download.")
        # messages.add_message(self.request, messages.SUCCESS, msg, extra_tags='success')
        # # except Exception as exc:
        # #     print(exc)
        # #     msg = _("An error occurred. Probably, your password is wrong.")
        # #     messages.add_message(self.request, messages.SUCCESS, msg, extra_tags='danger')
        # context = {'msg': render(self.request, 'common/messages.html').content.decode("utf-8")}
        # return self.render_to_json_response(context, safe=False)
        
        

class IssueAttachmentListView(IssueMixin, IssueCommentsContextMixin, AJAXRequestMixin, LoginRequiredMixin, generic.ListView):
    template_name = 'grm/issue_attachments.html'
    context_object_name = 'attachments'

    def get_queryset(self):
        # return self.doc['attachments'] if 'attachments' in self.doc else list()
        attr = self.request.GET.get('attr', 'attachments')
        if attr != 'attachments': 
            self.context_object_name = attr
        return self.doc[attr] if attr in self.doc else list()

    def dispatch(self, request, *args, **kwargs):
        column = self.request.GET.get('column', '')
        if column:
            # self.template_name = 'grm/issue_attachments_column1.html'
            self.template_name = 'grm/issue_attachments{}.html'.format(('_column'+column) if column else '')
        return super().dispatch(request, *args, **kwargs)


class IssueFormMixin(IssueMixin, generic.FormView):

    def get_form_kwargs(self):
        self.initial = {'doc_id': self.doc['_id'], 'user': self.request.user}
        return super().get_form_kwargs()


class NewIssueMixin(LoginRequiredMixin, IssueFormMixin):
    fields_to_check = None

    def dispatch(self, request, *args, **kwargs):
        dispatch = super().dispatch(request, *args, **kwargs)
        if not self.has_required_fields():
            raise Http404
        return dispatch

    def get_query_result(self, **kwargs):
        return self.grm_db.get_query_result({
            "auto_increment_id": kwargs['issue'],
            "reporter.id": self.request.user.id,
            "confirmed": False,
            "type": 'issue'
        })

    def get_form_kwargs(self):
        self.initial = {'doc_id': self.doc['_id']}
        return super().get_form_kwargs()

    def has_required_fields(self):
        if self.fields_to_check and self.doc:
            for field in self.fields_to_check:

                if field not in self.doc:
                    return False

                if field in ('assignee',) and not self.doc[field]:
                    return False
        return True

    def set_details_fields(self, data):
        self.doc['intake_date'] = data['intake_date'].strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        self.doc['issue_date'] = data['issue_date'].strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        
        if int(data['category']) in (4, 7) and data.get("issue_password"):
            self.request.session["issue_password"] = data.get("issue_password")
        if int(data['category']) in (4, 7) and self.request.POST.get("confirm") == "confirm":
            self.doc['description'] = str(cryptography_fernet_encrypt(data['description'], self.request.session["issue_password"]))
        else:
            self.doc['description'] = data['description']
        self.doc['publish'] = False

        try:
            # doc_type = self.grm_db.get_query_result({
            #     "id": int(data['issue_type']),
            #     "type": 'issue_type'
            # })[0][0]
            doc_category = self.grm_db.get_query_result({
                "id": int(data['category']),
                "type": 'issue_category'
            })[0][0]
            department_id = doc_category['assigned_department']['id']
        except Exception:
            raise Http404

        # self.doc['issue_type'] = {
        #     "id": doc_type['id'],
        #     "name": doc_type['name'],
        # }
        self.doc['issue_type'] = {
            "id": 1,
            "name": "Plainte"
        }
        assigned_department = doc_category['assigned_department'][
            'administrative_level'] if 'administrative_level' in doc_category['assigned_department'] else None
        self.doc['category'] = {
            "id": doc_category['id'],
            "name": doc_category['name'],
            "confidentiality_level": doc_category['confidentiality_level'],
            "assigned_department": department_id,
            "administrative_level": assigned_department,
        }
        self.doc['ongoing_issue'] = data['ongoing_issue']
        self.doc['event_recurrence'] = data['event_recurrence']
        self.doc['notification_send'] = False

        self.doc.save()

    def set_person_fields(self, data):
        self.doc['citizen'] = data['citizen']

        citizen_type = int(data['citizen_type']) if data['citizen_type'] else None
        self.doc['citizen_type'] = citizen_type

        if data['citizen'] and not citizen_type:
            self.doc['citizen_type'] = 0

        if data['citizen_age_group']:
            try:
                doc_issue_age_group = self.grm_db.get_query_result({
                    "id": int(data['citizen_age_group']),
                    "type": 'issue_age_group'
                })[0][0]
                self.doc['citizen_age_group'] = {
                    "name": doc_issue_age_group['name'],
                    "id": doc_issue_age_group['id']
                }
            except Exception:
                raise Http404
        else:
            self.doc['citizen_age_group'] = ""

        self.doc['gender'] = data['gender']

        if data.get('citizen_group_1'):
            try:
                doc_issue_citizen_group_1 = self.grm_db.get_query_result({
                    "id": int(data['citizen_group_1']),
                    "type": 'issue_citizen_group_1'
                })[0][0]
                self.doc['citizen_group_1'] = {
                    "name": doc_issue_citizen_group_1['name'],
                    "id": doc_issue_citizen_group_1['id']
                }
            except Exception:
                raise Http404
        else:
            self.doc['citizen_group_1'] = ""

        if data.get('citizen_group_2'):
            try:
                doc_issue_citizen_group_2 = self.grm_db.get_query_result({
                    "id": int(data['citizen_group_2']),
                    "type": 'issue_citizen_group_2'
                })[0][0]
                self.doc['citizen_group_2'] = {
                    "name": doc_issue_citizen_group_2['name'],
                    "id": doc_issue_citizen_group_2['id']
                }
            except Exception:
                raise Http404
        else:
            self.doc['citizen_group_2'] = ""
        
        self.doc['citizen_or_group'] = data['citizen_or_group']

    def set_location_fields(self, data):

        try:
            doc_administrative_level = self.adl_db.get_query_result({
                "administrative_id": data['administrative_region_value'],
                "type": 'administrative_level'
            })[0][0]
        except Exception:
            raise Http404

        self.doc['administrative_region'] = {
            "administrative_id": doc_administrative_level['administrative_id'],
            "name": doc_administrative_level['name'],
        }
        
        self.doc['location_info'] = {
            'issue_location': self.doc['administrative_region'],
            'location_description': data.get('location_description') if data.get('location_description') else '',
        }

        self.doc['structure_in_charge'] = {
            'name': data.get('structure_in_charge') if data.get('structure_in_charge') else '',
            'phone': data.get('structure_in_charge_phone') if data.get('structure_in_charge_phone') else '',
            'email': data.get('structure_in_charge_email') if data.get('structure_in_charge_email') else '',
        }



    def set_assignee(self):

        # try:
        assignee = get_assignee(self.grm_db, self.eadl_db, self.adl_db, self.doc)
        # except Exception:
            # raise Http404

        if assignee == "":
            msg = _("There is no staff member to assign the issue to. Please report to IT staff.")
            messages.add_message(self.request, messages.ERROR, msg, extra_tags='danger')

        self.doc['assignee'] = assignee

    def set_contact_fields(self, data):
        self.doc['contact_medium'] = data['contact_medium']
        if data['contact_medium'] == CHOICE_CONTACT:
            self.doc['contact_information'] = {
                "type": data['contact_type'],
                "contact": data['contact'],
            }
        else:
            self.doc['contact_information'] = None


class NewIssueContactFormView(PageMixin, NewIssueMixin):
    template_name = 'grm/new_issue_contact.html'
    title = _('GRM')
    active_level1 = 'grm'
    form_class = NewIssueContactForm

    def form_valid(self, form):
        data = form.cleaned_data
        try:
            self.set_contact_fields(data)
        except Exception as e:
            raise e
        self.doc.save()
        return HttpResponseRedirect(reverse('dashboard:grm:new_issue_step_2', kwargs={'issue': self.kwargs['issue']}))


class NewIssuePersonFormView(PageMixin, NewIssueMixin):
    template_name = 'grm/new_issue_person.html'
    title = _('GRM')
    active_level1 = 'grm'
    form_class = NewIssuePersonForm
    fields_to_check = ('contact_medium',)

    def form_valid(self, form):
        data = form.cleaned_data
        try:
            self.set_person_fields(data)
        except Exception as e:
            raise e
        self.doc.save()
        return HttpResponseRedirect(reverse('dashboard:grm:new_issue_step_3', kwargs={'issue': self.kwargs['issue']}))


class NewIssueDetailsFormView(PageMixin, NewIssueMixin):
    template_name = 'grm/new_issue_details.html'
    title = _('GRM')
    active_level1 = 'grm'
    form_class = NewIssueDetailsForm
    fields_to_check = ('contact_medium', 'citizen')

    def form_valid(self, form):
        data = form.cleaned_data
        self.set_details_fields(data)
        self.doc.save()
        return HttpResponseRedirect(reverse('dashboard:grm:new_issue_step_4', kwargs={'issue': self.kwargs['issue']}))


class NewIssueLocationFormView(PageMixin, NewIssueMixin):
    template_name = 'grm/new_issue_location.html'
    title = _('GRM')
    active_level1 = 'grm'
    form_class = NewIssueLocationForm
    fields_to_check = ('contact_medium', 'intake_date', 'issue_date', 
                    #    'issue_type', 
                       'category', 'description',
                       'ongoing_issue', 'event_recurrence')

    def form_valid(self, form):
        data = form.cleaned_data
        self.set_location_fields(data)
        print(7)
        self.set_assignee()
        print(8)
        self.doc.save()
        if not self.doc['assignee']:
            return HttpResponseRedirect(
                reverse('dashboard:grm:new_issue_step_4', kwargs={'issue': self.kwargs['issue']}))
        return HttpResponseRedirect(reverse('dashboard:grm:new_issue_step_5', kwargs={'issue': self.kwargs['issue']}))


class NewIssueConfirmFormView(PageMixin, NewIssueMixin):
    template_name = 'grm/new_issue_confirm.html'
    title = _('GRM')
    active_level1 = 'grm'
    form_class = NewIssueConfirmForm
    fields_to_check = ('contact_medium', 'intake_date', 'issue_date', 
                    #    'issue_type', 
                       'category', 'description',
                       'ongoing_issue', 'event_recurrence', 'assignee', 'administrative_region')

    def form_valid(self, form):
        data = form.cleaned_data
        try:
            self.set_contact_fields(data)
            self.set_person_fields(data)
            self.set_details_fields(data)
            self.set_location_fields(data)
            self.set_assignee()

            try:
                send_a_new_issue_notification()
            except:
                pass
        except Exception as e:
            raise e

        if not self.doc['assignee']:
            return HttpResponseRedirect(
                reverse('dashboard:grm:new_issue_step_5', kwargs={'issue': self.kwargs['issue']}))

        self.set_contact_fields(data)
        try:
            doc_category = self.grm_db.get_query_result({
                "id": self.doc['category']['id'],
                "type": 'issue_category'
            })[0][0]
        except Exception:
            raise Http404
        administrative_id = self.doc["administrative_region"]["administrative_id"]
        self.doc[
            'internal_code'] = f'{doc_category["abbreviation"]}-{administrative_id}-{self.doc["auto_increment_id"]}'

        try:
            doc_status = self.grm_db.get_query_result({
                "initial_status": True,
                "type": 'issue_status'
            })[0][0]
        except Exception:
            raise Http404
        self.doc['status'] = {
            "name": doc_status['name'],
            "id": doc_status['id']
        }

        self.doc['created_date'] = datetime.now().strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        self.doc['confirmed'] = True
        self.doc['source'] = "web"
        self.doc['comments'] = []
        anonymize_issue_data(self.doc)

        self.request.session["issue_password"] = None
        self.doc.save()
        return HttpResponseRedirect(reverse('dashboard:grm:new_issue_step_6', kwargs={'issue': self.kwargs['issue']}))


class NewIssueConfirmationFormView(PageMixin, NewIssueMixin):
    template_name = 'grm/new_issue_confirmation.html'
    title = _('GRM')
    active_level1 = 'grm'
    form_class = NewIssueConfirmForm
    permissions = ('read_only_by_reporter',)

    def get_query_result(self, **kwargs):
        return self.grm_db.get_query_result({
            "auto_increment_id": kwargs['issue'],
            "confirmed": True,
            "type": 'issue'
        })


class ReviewIssuesFormView(PageMixin, LoginRequiredMixin, generic.FormView):
    form_class = SearchIssueForm
    template_name = 'grm/review_issues.html'
    title = _('Review Issues')
    active_level1 = 'grm'
    breadcrumb = [
        {
            'url': reverse_lazy('dashboard:grm:dashboard'),
            'title': _('GRM')
        },
        {
            'url': '',
            'title': title
        }
    ]
    
    def dispatch(self, request, *args, **kwargs):
        check_issues()
        escalate_issues()
        send_sms_message()
        send_a_new_issue_notification()
        return super().dispatch(request, *args, **kwargs)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        context['publish_option'] = False
        if user.groups.filter().exists():
            #user.groups.filter(name="Admin").exists() or (hasattr(user, 'governmentworker') and user.governmentworker.administrative_id != "1"):
            context['publish_option'] = True
        return context


class IssueListView(AJAXRequestMixin, LoginRequiredMixin, generic.ListView):
    template_name = 'grm/issue_list.html'
    context_object_name = 'issues'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        index = int(self.request.GET.get('index'))
        offset = int(self.request.GET.get('offset'))
        issues = self.get_results()
        context['total_issues'] = len(list(issues))
        context['issues'] = issues[index:index + offset]
        return context
    
    def get_queryset(self):
        # index = int(self.request.GET.get('index'))
        # offset = int(self.request.GET.get('offset'))
        # return self.get_results()[index:index + offset]
        return []
    
    def get_results(self):
        grm_db = get_db(COUCHDB_GRM_DATABASE)
        adl_db = get_db(COUCHDB_DATABASE_ADMINISTRATIVE_LEVEL)
        index = int(self.request.GET.get('index'))
        offset = int(self.request.GET.get('offset'))
        start_date = self.request.GET.get('start_date')
        end_date = self.request.GET.get('end_date')
        code = self.request.GET.get('code')
        assigned_to = self.request.GET.get('assigned_to')
        category = self.request.GET.get('category')
        # issue_type = self.request.GET.get('type')
        status = self.request.GET.get('status')
        other = self.request.GET.get('other')
        region = self.request.GET.get('region')
        reported_by = self.request.GET.get('reported_by')
        publish = self.request.GET.get('publish')
        user = self.request.user

        if user.groups.filter(name__in=["Admin", "ViewerOfAllIssues"]).exists():
            selector = {
                "type": "issue",
                "confirmed": True,
                "auto_increment_id": {"$ne": ""},
            }
        else:
            selector = {
                "type": "issue",
                "confirmed": True,
                "auto_increment_id": {"$ne": ""},
            }
            
            if hasattr(user, 'governmentworker') and user.governmentworker.administrative_id != "1":
                parent_ids = user.governmentworker.all_administrative_ids
                # descendants = get_administrative_level_descendants(adl_db, parent_id, []) 
                
                # parent_id = user.governmentworker.administrative_id
                # descendants = get_administrative_level_descendants_using_mis(adl_db, parent_id, [], self.request.user)
                # allowed_regions = descendants + [parent_id]
                
                descendants = []
                for p_id in parent_ids:
                    descendants += get_administrative_level_descendants_using_mis(adl_db, p_id, [], self.request.user)
                allowed_regions = descendants + parent_ids

                selector["$or"] = [
                    {"assignee.id": user.id},
                    {"$and": [
                        {"category.assigned_department": user.governmentworker.department},
                        {"administrative_region.administrative_id": {"$in": allowed_regions}},
                    ]}
                ]
            else:
                selector = {
                    "type": "issue",
                    "publish": True,
                    "confirmed": True,
                    "auto_increment_id": {"$ne": ""},
                }

        date_range = {}
        if start_date:
            start_date = datetime.strptime(start_date, '%d/%m/%Y').strftime('%Y-%m-%dT%H:%M:%S.%fZ')
            date_range["$gte"] = start_date
            selector["intake_date"] = date_range
        if end_date:
            end_date = (datetime.strptime(end_date, '%d/%m/%Y') + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
            date_range["$lte"] = end_date
            selector["intake_date"] = date_range
        if code:
            code_filter = {"$regex": f"^{code}"}
            selector['$or'] = [{"internal_code": code_filter}, {"tracking_code": code_filter},
                               {"description": code_filter}]
        if assigned_to:
            selector["assignee.id"] = int(assigned_to)
        if category:
            selector["category.id"] = int(category)
        # if issue_type:
        #     selector["issue_type.id"] = int(issue_type)
        if status:
            selector["status.id"] = int(status)
        if other:
            if other == "Escalate":
                selector["escalation_reasons"] = {"$exists": True}
        if reported_by:
            selector["reporter.id"] = int(reported_by)
        if publish in ('True', 'False'):
            selector["publish"] = True if publish == 'True' else False

        if region:
            # filter_regions = get_administrative_level_descendants(adl_db, region, []) + [region]
            filter_regions = get_administrative_level_descendants_using_mis(adl_db, region, [], self.request.user) + [region]
            
            selector["administrative_region.administrative_id"] = {
                "$in": filter_regions
            }
        # _query_result = grm_db.get_query_result(selector)[:]
        # _ = _query_result
        # for elt in _query_governmentworker:
        #     if elt not in _query_result:
        #         _.append(elt)
        return grm_db.get_query_result(selector)



class IssueDetailsFormView(PageMixin, IssueMixin, IssueCommentsContextMixin, LoginRequiredMixin, generic.FormView):
    form_class = IssueDetailsForm
    template_name = 'grm/issue_detail.html'
    title = _('Issue Detail')
    active_level1 = 'grm'
    breadcrumb = [
        {
            'url': reverse_lazy('dashboard:grm:dashboard'),
            'title': _('GRM')
        },
        {
            'url': reverse_lazy('dashboard:grm:review_issues'),
            'title': _('Review Issues')
        },
        {
            'url': '',
            'title': title
        }
    ]

    def get_form_kwargs(self):
        self.initial = {'doc_id': self.doc['_id']}
        return super().get_form_kwargs()

    def get_query_result(self, **kwargs):
        return self.grm_db.get_query_result({
            "auto_increment_id": kwargs['issue'],
            # # "confirmed": True,
            # # "type": 'issue'
        })

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user_id = self.request.user.id
        user = self.request.user

        if user.groups.filter(name__in=["Admin", "ViewerOfAllIssues"]).exists():
            pass
        else:
            if not self.doc.get('publish'):
                raise PermissionDenied


        self.specific_permissions()

        context['enable_add_comment'] = user_id == (self.doc['assignee']['id'] if type(self.doc['assignee']) == dict else 0) or user_id == self.doc_department[
            'head']['id'] or user.groups.filter(name="Admin").exists()

        if not context['enable_add_comment'] and hasattr(user, 'governmentworker') and self.doc and "administrative_region" in self.doc and "administrative_id" in self.doc["administrative_region"]:
            # parent_id = user.governmentworker.administrative_id
            # descendants = get_administrative_level_descendants_using_mis(None, parent_id, [], self.request.user)
            # allowed_regions = descendants + [parent_id]

            parent_ids = user.governmentworker.all_administrative_ids
            descendants = []
            for _id in parent_ids:
                descendants += get_administrative_level_descendants_using_mis(None, _id, [], self.request.user)
            allowed_regions = descendants + parent_ids

            if self.doc["administrative_region"]["administrative_id"] in allowed_regions:
                context['enable_add_comment'] = True

        context['comment_form'] = IssueCommentForm()
        context['reason_comment_form'] = IssueReasonCommentForm()
        try:
            doc_status = self.grm_db.get_query_result({
                "id": self.doc['status']['id'],
                "type": 'issue_status'
            })[0][0]
        except Exception:
            raise Http404
        context['doc_status'] = doc_status
        context['password_confirm_form'] = PasswordConfirmForm()
        context['category_form'] = IssueCategoryForm(
            initial= {'doc_id': self.doc['_id'], 'user': self.request.user}
        )
        
        
        escalate_issues()
        send_a_new_issue_notification()

        return context


class EditIssueView(IssueMixin, AJAXRequestMixin, LoginRequiredMixin, JSONResponseMixin, generic.View):
    permissions = ('read',)

    def post(self, request, *args, **kwargs):
        assignee = int(request.POST.get('assignee'))
        worker = GovernmentWorker.objects.get(user=assignee)
        self.doc['assignee'] = {
            "id": worker.user.id,
            "name": worker.name
        }
        self.doc.save()
        msg = _("The issue was successfully edited.")
        messages.add_message(self.request, messages.SUCCESS, msg, extra_tags='success')
        context = {'msg': render(self.request, 'common/messages.html').content.decode("utf-8")}
        return self.render_to_json_response(context, safe=False)


class EditIssueCategoryView(IssueMixin, AJAXRequestMixin, AdminPermissionRequiredMixin, JSONResponseMixin, generic.View):
    permissions = ('read',)

    def post(self, request, *args, **kwargs):
        category_id = int(request.POST.get('category_id'))
        
        try:
            doc_category = self.grm_db.get_query_result({
                "id": int(category_id),
                "type": 'issue_category'
            })[0][0]
            department_id = doc_category['assigned_department']['id']
        except Exception:
            raise Http404
        
        comments = self.doc['comments'] if 'comments' in self.doc else list()
        comment_obj = {
            "name": self.request.user.name,
            "id": self.request.user.id,
            "comment": f'{_("Category change")} : \"{self.doc["category"]["name"]}\" {_("to")} \"{doc_category["name"]}\"',
            "due_at": datetime.now().strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        }
        comments.insert(0, comment_obj)
        self.doc['comments'] = comments

        
        assigned_department = doc_category['assigned_department'][
            'administrative_level'] if 'administrative_level' in doc_category['assigned_department'] else None
        self.doc['category'] = {
            "id": doc_category['id'],
            "name": doc_category['name'],
            "confidentiality_level": doc_category['confidentiality_level'],
            "assigned_department": department_id,
            "administrative_level": assigned_department,
        }

        self.doc.save()
        msg = _("The issue was successfully edited.")
        messages.add_message(self.request, messages.SUCCESS, msg, extra_tags='success')
        context = {'msg': render(self.request, 'common/messages.html').content.decode("utf-8")}
        return self.render_to_json_response(context, safe=False)
    


class AddCommentToIssueView(IssueMixin, AJAXRequestMixin, LoginRequiredMixin, JSONResponseMixin, generic.View):

    def post(self, request, *args, **kwargs):
        try:
            doc_department = self.grm_db.get_query_result({
                "id": self.doc['category']['assigned_department'],
                "type": 'issue_department'
            })[0][0]
        except Exception:
            raise Http404
        user_id = request.user.id
        if self.doc['assignee'] and user_id != self.doc['assignee']['id'] and user_id != doc_department['head']['id']:
            raise PermissionDenied()

        reason = self.request.GET.get('reason', '')
        
        # comment = request.POST.get('comment').strip()[:MAX_LENGTH]
        comment = request.POST.get('comment').strip()

        if not reason:
            comment[:MAX_LENGTH]

        if comment:
            comments = self.doc['comments'] if 'comments' in self.doc else list()
            reasons = self.doc['reasons'] if 'reasons' in self.doc else list()

            issue_password = request.POST.get('issue_password_reason') if request.POST.get('issue_password_reason') else request.POST.get('issue_password_comment')
            
            
            _ok = True
            if  self.doc['category']["id"] in (4, 7): # and issue_password:
                last_category_password = get_last_category_password(self.doc['category']["id"])
                if not last_category_password:
                    msg = _("The information has not been registered. No password is defined for this category of complaint.")
                    messages.add_message(self.request, messages.ERROR, msg, extra_tags='error')
                    _ok = False
                elif not check_password(issue_password, last_category_password.password):
                    msg = _("The information has not been saved. The password does not match.")
                    messages.add_message(self.request, messages.ERROR, msg, extra_tags='error')
                    _ok = False
                else:
                    comment = str(cryptography_fernet_encrypt(comment, issue_password))
            if _ok:
                due_at = datetime.now().strftime('%Y-%m-%dT%H:%M:%S.%fZ')
                if reason:
                    comment_obj = {
                        "user_name": request.user.name,
                        "user_id": user_id,
                        "comment": comment,
                        "due_at": due_at,
                        "id": due_at,
                        "type": "comment"
                    }
                    reasons.insert(0, comment_obj)
                    self.doc['reasons'] = reasons
                else:
                    comment_obj = {
                        "name": request.user.name,
                        "id": user_id,
                        "comment": comment,
                        "due_at": due_at
                    }
                    comments.insert(0, comment_obj)
                    self.doc['comments'] = comments
                self.doc.save()
                msg = _("The comment was sent successfully.")
                messages.add_message(self.request, messages.SUCCESS, msg, extra_tags='success')
        else:
            msg = _("Comment cannot be empty.")
            messages.add_message(self.request, messages.ERROR, msg, extra_tags='danger')
        
        if _ok:
            context = {'msg': render(self.request, 'common/messages.html').content.decode("utf-8")}
        else:
            context = {
                'msg': render(self.request, 'common/messages.html').content.decode("utf-8"),
                'comment': comment
            }
        return self.render_to_json_response(context, safe=False)


class IssueCommentListView(IssueMixin, IssueCommentsContextMixin, AJAXRequestMixin, LoginRequiredMixin,
                           generic.ListView):
    template_name = 'grm/issue_comments.html'
    context_object_name = 'comments'
    permissions = ('read',)

    def get_queryset(self):
        return self.doc['comments'] if 'comments' in self.doc else list()


class IssueStatusButtonsTemplateView(IssueMixin, AJAXRequestMixin, LoginRequiredMixin, generic.TemplateView):
    template_name = 'grm/issue_status_buttons.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        try:
            doc_status = self.grm_db.get_query_result({
                "id": self.doc['status']['id'],
                "type": 'issue_status'
            })[0][0]
        except Exception:
            raise Http404
        context['doc_status'] = doc_status


        escalation_administrativelevels = self.doc['escalation_administrativelevels'] if 'escalation_administrativelevels' in self.doc else list()
        if not escalation_administrativelevels:
            try:
                context['current_adl_obj'] = {
                    'escalate_to': {
                    'administrative_id': self.doc['administrative_region']['administrative_id'],
                    'name': self.doc['administrative_region']['name'],
                    'administrative_level': self.doc['category']['administrative_level']
                    },
                    'due_at': self.doc['issue_date']
                }
            except:
                context['current_adl_obj'] = {
                    'escalate_to': {
                    'administrative_id': self.doc['administrative_region'],
                    'administrative_level': self.doc['category']['administrative_level']
                    },
                    'due_at': self.doc['issue_date']
                }
        else:
            context['current_adl_obj'] = escalation_administrativelevels[0]

        return context


class SubmitIssueOpenStatusView(AJAXRequestMixin, ModalFormMixin, LoginRequiredMixin, JSONResponseMixin,
                                        IssueFormMixin):
    form_class = IssueOpenStatusForm
    id_form = "open_reason_form"
    title = _('Enter a comment')
    submit_button = _('Save')
    permissions = ('read',)

    def check_permissions(self):
        super().check_permissions()
        # try:
        #     doc_status = self.grm_db.get_query_result({
        #         "id": self.doc["status"]["id"],
        #         "type": 'issue_status'
        #     })[0][0]
        # except Exception:
        #     self.has_permission = False
        #     return

        # open_status = doc_status['open_status'] if 'open_status' in doc_status else False
        # initial_status = doc_status['initial_status'] if 'initial_status' in doc_status else False
        # rejected_status = doc_status['rejected_status'] if 'rejected_status' in doc_status else False
        # if open_status or not initial_status or rejected_status:
        #     self.has_permission = False

    def form_valid(self, form):
        # self.doc['research_result'] = ""
        # self.doc['reject_reason'] = ""
        data = form.cleaned_data
        self.doc['open_reason'] = data["open_reason"]
        self.doc['_comment'] = data["open_reason"]
        
        try:
            doc_status = self.grm_db.get_query_result({
                "open_status": True,
                "type": 'issue_status'
            })[0][0]
        except Exception:
            raise Http404
        self.doc['status'] = {
            "name": doc_status['name'],
            "id": doc_status['id']
        }
        self.doc['open_date'] = datetime.now().strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        self.doc["issue_status_stories"] = get_issue_status_stories(self.request.user, self.doc, self.doc['status'])
        del self.doc['_comment']

        comments = self.doc['comments'] if 'comments' in self.doc else list()
        comment_obj = {
            "name": self.request.user.name,
            "id": self.request.user.id,
            "issue_status": _("Issue opened").__str__(),
            "comment": data["open_reason"],
            "due_at": datetime.now().strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        }
        comments.insert(0, comment_obj)
        self.doc['comments'] = comments

        self.doc.save()
        msg = _("The issue status was successfully updated.")
        messages.add_message(self.request, messages.SUCCESS, msg, extra_tags='success')
        context = {'msg': render(self.request, 'common/messages.html').content.decode("utf-8")}
        return self.render_to_json_response(context, safe=False)


class SubmitIssueResearchResultFormView(AJAXRequestMixin, ModalFormMixin, LoginRequiredMixin, JSONResponseMixin,
                                        IssueFormMixin):
    form_class = IssueResearchResultForm
    id_form = "research_result_form"
    title = _('Please enter the resolution reached for this issue')
    submit_button = _('Save')
    permissions = ('read',)

    def check_permissions(self):
        super().check_permissions()
        # try:
        #     doc_status = self.grm_db.get_query_result({
        #         "id": self.doc["status"]["id"],
        #         "type": 'issue_status'
        #     })[0][0]
        # except Exception:
        #     self.has_permission = False
        #     return

        # open_status = doc_status['open_status'] if 'open_status' in doc_status else False
        # final_status = doc_status['final_status'] if 'final_status' in doc_status else False
        # if final_status or not open_status:
        #     self.has_permission = False

    def form_valid(self, form):
        data = form.cleaned_data
        issue_password = data['issue_password'] if 'issue_password' in data else None
        _ok = True
        _comment = data["research_result"]
        if  self.doc['category']["id"] in (4, 7): # and issue_password:
            last_category_password = get_last_category_password(self.doc['category']["id"])
            if not last_category_password:
                msg = _("The information has not been registered. No password is defined for this category of complaint.")
                messages.add_message(self.request, messages.ERROR, msg, extra_tags='error')
                _ok = False
            elif not check_password(issue_password, last_category_password.password):
                msg = _("The information has not been saved. The password does not match.")
                messages.add_message(self.request, messages.ERROR, msg, extra_tags='error')
                _ok = False
            else:
                _comment = str(cryptography_fernet_encrypt(_comment, issue_password))

        if _ok:
            self.doc['research_result'] = _comment
            self.doc['_comment'] = _comment
            # self.doc['reject_reason'] = ""
            try:
                doc_status = self.grm_db.get_query_result({
                    "final_status": True,
                    "type": 'issue_status'
                })[0][0]
            except Exception:
                raise Http404
            self.doc['status'] = {
                "name": doc_status['name'],
                "id": doc_status['id']
            }
            self.doc['resolution_date'] = datetime.now().strftime('%Y-%m-%dT%H:%M:%S.%fZ')
            self.doc["issue_status_stories"] = get_issue_status_stories(self.request.user, self.doc, self.doc['status'])
            del self.doc['_comment']

            comments = self.doc['comments'] if 'comments' in self.doc else list()
            comment_obj = {
                "name": self.request.user.name,
                "id": self.request.user.id,
                "issue_status": _("Issue resolved").__str__(),
                "comment": _comment,
                "due_at": datetime.now().strftime('%Y-%m-%dT%H:%M:%S.%fZ')
            }
            comments.insert(0, comment_obj)
            self.doc['comments'] = comments


            # File
            reasons = self.doc['reasons'] if 'reasons' in self.doc else list()
            
            file = data['file_pdf']
            
            if  file and self.doc.get('category') and self.doc['category']["id"] in (4, 7) and issue_password:
                    file = cryptography_fernet_encrypt(file, issue_password,  _type="file", filename=file.name)
                    file.name = f'encrypt_{file.name}' if 'encrypt_' not in file.name else file.name
            
            if file:
                response = upload_file(file, COUCHDB_GRM_ATTACHMENT_DATABASE)
                if response['ok']:
                    attachment = {
                        "name": file.name,
                        "url": f'/grm_attachments/{response["id"]}/{file.name}',
                        "local_url": "",
                        "id": datetime.now().strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
                        "uploaded": True,
                        "bd_id": response['id'],
                        "subject": "resolution"
                    }
                    
                    attachment["type"] = "file"
                    attachment["user_id"] = self.request.user.id
                    attachment["user_name"] = self.request.user.name
                    reasons.insert(0, attachment)
                    self.doc['reasons'] = reasons

                    resolution_files = self.doc['resolution_files'] if 'resolution_files' in self.doc else list()
                    resolution_files.insert(0, attachment)
                    self.doc['resolution_files'] = resolution_files
                    
            # End File



            self.doc.save()
            msg = _("The issue status was successfully updated.")
            messages.add_message(self.request, messages.SUCCESS, msg, extra_tags='success')

        context = {'msg': render(self.request, 'common/messages.html').content.decode("utf-8")}
        return self.render_to_json_response(context, safe=False)

class SubmitIssueSetUnresolvedFormView(AJAXRequestMixin, ModalFormMixin, LoginRequiredMixin, JSONResponseMixin,
                                        IssueFormMixin):
    form_class = IssueSetUnresolvedForm
    id_form = "unresolved_reason_form"
    title = _('Please enter the reason for changing the status to unresolved for this issue')
    submit_button = _('Save')
    permissions = ('read',)

    def check_permissions(self):
        super().check_permissions()

    def form_valid(self, form):
        data = form.cleaned_data
        self.doc['unresolved_reason'] = data["unresolved_reason"]
        self.doc['_comment'] = data["unresolved_reason"]
        try:
            doc_status = self.grm_db.get_query_result({
                "unresolved_status": True,
                "type": 'issue_status'
            })[0][0]
        except Exception:
            raise Http404
        self.doc['status'] = {
            "name": doc_status['name'],
            "id": doc_status['id']
        }
        self.doc['unresolved_date'] = datetime.now().strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        self.doc["issue_status_stories"] = get_issue_status_stories(self.request.user, self.doc, self.doc['status'])
        del self.doc['_comment']

        comments = self.doc['comments'] if 'comments' in self.doc else list()
        comment_obj = {
            "name": self.request.user.name,
            "id": self.request.user.id,
            "issue_status": _("Unresolved Issue").__str__(),
            "comment": data["unresolved_reason"],
            "due_at": datetime.now().strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        }
        comments.insert(0, comment_obj)
        self.doc['comments'] = comments

        self.doc.save()
        msg = _("The issue status was successfully updated.")
        messages.add_message(self.request, messages.SUCCESS, msg, extra_tags='success')

        context = {'msg': render(self.request, 'common/messages.html').content.decode("utf-8")}
        return self.render_to_json_response(context, safe=False)


class SubmitIssueEscalateFormView(AJAXRequestMixin, ModalFormMixin, LoginRequiredMixin, JSONResponseMixin,
                                        IssueFormMixin):
    form_class = IssueIssueEscalateForm
    id_form = "escalate_reason_form"
    title = _('Please enter the reason of the escalate for this issue')
    submit_button = _('Save')
    permissions = ('read',)

    def check_permissions(self):
        super().check_permissions()

    def form_valid(self, form):
        data = form.cleaned_data
        issue_password = data['issue_password'] if 'issue_password' in data else None
        _ok = True
        _comment = data["escalate_reason"]
        if  self.doc['category']["id"] in (4, 7): # and issue_password:
            last_category_password = get_last_category_password(self.doc['category']["id"])
            if not last_category_password:
                msg = _("The information has not been registered. No password is defined for this category of complaint.")
                messages.add_message(self.request, messages.ERROR, msg, extra_tags='error')
                _ok = False
            elif not check_password(issue_password, last_category_password.password):
                msg = _("The information has not been saved. The password does not match.")
                messages.add_message(self.request, messages.ERROR, msg, extra_tags='error')
                _ok = False
            else:
                _comment = str(cryptography_fernet_encrypt(_comment, issue_password))

        if _ok:
            self.doc['escalate_reason'] = _comment
            self.doc['_comment'] = _comment
            
            self.doc['escalate_flag'] = True
            self.doc['escalate_date'] = datetime.now().strftime('%Y-%m-%dT%H:%M:%S.%fZ')
            self.doc["issue_status_stories"] = get_issue_status_stories(self.request.user, self.doc, self.doc['status'])
            del self.doc['_comment']

            comments = self.doc['comments'] if 'comments' in self.doc else list()
            escalation_reasons = self.doc['escalation_reasons'] if 'escalation_reasons' in self.doc else list()
            comment_obj = {
                "name": self.request.user.name,
                "id": self.request.user.id,
                "issue_status": _("Issue escalated").__str__(),
                "comment": _comment,
                "due_at": datetime.now().strftime('%Y-%m-%dT%H:%M:%S.%fZ')
            }
            comments.insert(0, comment_obj)
            self.doc['comments'] = comments

            # File
            reasons = self.doc['reasons'] if 'reasons' in self.doc else list()
            comment_obj["type"] = "comment"
            comment_obj["user_id"] = self.request.user.id
            comment_obj["user_name"] = self.request.user.name
            reasons.insert(0, comment_obj)
            
            file = data['file_pdf']
            
            if  file and self.doc.get('category') and self.doc['category']["id"] in (4, 7) and issue_password:
                    file = cryptography_fernet_encrypt(file, issue_password,  _type="file", filename=file.name)
                    file.name = f'encrypt_{file.name}' if 'encrypt_' not in file.name else file.name
            
            if file:
                response = upload_file(file, COUCHDB_GRM_ATTACHMENT_DATABASE)
                if response['ok']:
                    attachment = {
                        "name": file.name,
                        "url": f'/grm_attachments/{response["id"]}/{file.name}',
                        "local_url": "",
                        "id": datetime.now().strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
                        "uploaded": True,
                        "bd_id": response['id'],
                        "subject": "escalation"
                    }
                    
                    attachment["type"] = "file"
                    attachment["user_id"] = self.request.user.id
                    attachment["user_name"] = self.request.user.name
                    reasons.insert(0, attachment)
                    self.doc['reasons'] = reasons

                    del comment_obj['type']
                    comment_obj['attachment'] = attachment
                    
            # End File

            escalation_reasons.insert(0, comment_obj)
            self.doc['escalation_reasons'] = escalation_reasons

            self.doc.save()

            escalate_issues()

            msg = _("The issue status was successfully updated.")
            messages.add_message(self.request, messages.SUCCESS, msg, extra_tags='success')

        context = {'msg': render(self.request, 'common/messages.html').content.decode("utf-8")}
        return self.render_to_json_response(context, safe=False)
    


class SubmitIssuePublishFormView(AJAXRequestMixin, ModalFormMixin, LoginRequiredMixin, JSONResponseMixin,
                                        IssueFormMixin):
    form_class = IssueIssuePublishForm
    id_form = "issue_publish_form"
    title = _('Please edit the description before publish')
    submit_button = _('Publish')
    permissions = ('read',)

    def check_permissions(self):
        self.has_permission = False
        if self.request.user.groups.filter(name__in=["Admin"]).exists():
            self.has_permission = True

    def form_valid(self, form):
        data = form.cleaned_data
        issue_password = data.get("issue_password")
        last_category_password = get_last_category_password(self.doc['category']["id"])
        if not last_category_password:
            msg = _("The complaint has not been published. No password is defined for this category of complaint.")
            messages.add_message(self.request, messages.ERROR, msg, extra_tags='error')
        elif not check_password(issue_password, last_category_password.password):
            msg = _("The complaint has not been published. The password does not match.")
            messages.add_message(self.request, messages.ERROR, msg, extra_tags='error')
        else:
            if not self.doc.get('original_description'):
                if self.doc['category']["id"] in (4, 7):
                    self.doc['original_description'] = self.doc.get('description')
                    self.doc['description'] = str(cryptography_fernet_encrypt(data["issue_description"], issue_password))
                else:
                    self.doc['original_description'] = str(cryptography_fernet_encrypt(self.doc.get('description'), issue_password))
                    self.doc['description'] = data["issue_description"]
            else:
                if self.doc['category']["id"] in (4, 7):
                    self.doc[f"description_{datetime.now().strftime('%Y-%m-%dT%H:%M:%S.%fZ')}"] = self.doc.get('description')
                    self.doc['description'] = str(cryptography_fernet_encrypt(data["issue_description"], issue_password))
                else:
                    self.doc[f"description_{datetime.now().strftime('%Y-%m-%dT%H:%M:%S.%fZ')}"] = str(cryptography_fernet_encrypt(self.doc.get('description'), issue_password))
                    self.doc['description'] = data["issue_description"]
            
            self.doc['publish'] = True
            self.doc['publish_date'] = datetime.now().strftime('%Y-%m-%dT%H:%M:%S.%fZ')
            
            self.doc.save()
            msg = _("The issue status was successfully updated.")
            messages.add_message(self.request, messages.SUCCESS, msg, extra_tags='success')

        context = {'msg': render(self.request, 'common/messages.html').content.decode("utf-8")}
        return self.render_to_json_response(context, safe=False)
    

class SubmitIssueUnpublishFormView(AJAXRequestMixin, ModalFormMixin, LoginRequiredMixin, JSONResponseMixin,
                                        IssueFormMixin):
    form_class = IssueIssueUnpublishForm
    id_form = "issue_unpublish_form"
    title = _('Hide issue')
    submit_button = _('Unpublish')
    permissions = ('read',)

    def check_permissions(self):
        self.has_permission = False
        if self.request.user.groups.filter(name__in=["Admin"]).exists():
            self.has_permission = True

    def form_valid(self, form):
        self.doc['publish'] = False
        self.doc['unpublish_date'] = datetime.now().strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        self.doc.save()
        msg = _("The issue status was successfully updated.")
        messages.add_message(self.request, messages.SUCCESS, msg, extra_tags='success')

        context = {'msg': render(self.request, 'common/messages.html').content.decode("utf-8")}
        return self.render_to_json_response(context, safe=False)


class SubmitIssueRejectReasonFormView(AJAXRequestMixin, ModalFormMixin, LoginRequiredMixin, JSONResponseMixin,
                                      IssueFormMixin):
    form_class = IssueRejectReasonForm
    id_form = "reject_reason_form"
    title = _('Enter the reason for rejecting this issue')
    submit_button = _('Save')
    permissions = ('read',)

    def check_permissions(self):
        super().check_permissions()
        # try:
        #     doc_status = self.grm_db.get_query_result({
        #         "id": self.doc["status"]["id"],
        #         "type": 'issue_status'
        #     })[0][0]
        # except Exception:
        #     self.has_permission = False
        #     return

        # initial_status = doc_status['initial_status'] if 'initial_status' in doc_status else False
        # rejected_status = doc_status['rejected_status'] if 'rejected_status' in doc_status else False
        # if rejected_status or not initial_status:
        #     self.has_permission = False

    def form_valid(self, form):
        data = form.cleaned_data
        self.doc['reject_reason'] = data["reject_reason"]
        self.doc['_comment'] = data["reject_reason"]
        # self.doc['research_result'] = ""
        try:
            doc_status = self.grm_db.get_query_result({
                "rejected_status": True,
                "type": 'issue_status'
            })[0][0]
        except Exception:
            raise Http404
        self.doc['status'] = {
            "name": doc_status['name'],
            "id": doc_status['id']
        }
        self.doc['reject_date'] = datetime.now().strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        self.doc["issue_status_stories"] = get_issue_status_stories(self.request.user, self.doc, self.doc['status'])
        del self.doc['_comment']

        comments = self.doc['comments'] if 'comments' in self.doc else list()
        comment_obj = {
            "name": self.request.user.name,
            "id": self.request.user.id,
            "issue_status": _("Issue rejected").__str__(),
            "comment": data["open_reason"],
            "due_at": datetime.now().strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        }
        comments.insert(0, comment_obj)
        self.doc['comments'] = comments
        
        self.doc.save()
        msg = _("The issue status was successfully updated.")
        messages.add_message(self.request, messages.SUCCESS, msg, extra_tags='success')

        context = {'msg': render(self.request, 'common/messages.html').content.decode("utf-8")}
        return self.render_to_json_response(context, safe=False)


class GetChoicesForNextAdministrativeLevelView(AJAXRequestMixin, LoginRequiredMixin, JSONResponseMixin, generic.View):
    def get(self, request, *args, **kwargs):
        parent_id = request.GET.get('parent_id')
        exclude_lower_level = request.GET.get('exclude_lower_level', None)
        adl_db = get_db(COUCHDB_DATABASE_ADMINISTRATIVE_LEVEL)
        # data = get_child_administrative_regions(adl_db, parent_id)
        data = get_child_administrative_regions_using_mis(adl_db, parent_id, request.user)
        
        # if data and exclude_lower_level and not get_child_administrative_regions(adl_db, data[0]['administrative_id']):
        if data and exclude_lower_level and not get_child_administrative_regions_using_mis(adl_db, data[0]['administrative_id'], request.user):
            data = []

        return self.render_to_json_response(data, safe=False)


class GetAncestorAdministrativeLevelsView(AJAXRequestMixin, LoginRequiredMixin, JSONResponseMixin, generic.View):
    def get(self, request, *args, **kwargs):
        administrative_id = request.GET.get('administrative_id', None)
        ancestors = []
        if administrative_id:
            adl_db = get_db(COUCHDB_DATABASE_ADMINISTRATIVE_LEVEL)
            has_parent = True
            while has_parent:
                parent = get_parent_administrative_level(adl_db, administrative_id)
                if parent:
                    administrative_id = parent['administrative_id']
                    ancestors.insert(0, administrative_id)
                else:
                    has_parent = False

        return self.render_to_json_response(ancestors, safe=False)


class GetSensitiveIssueDataView(IssueMixin, AJAXRequestMixin, LoginRequiredMixin, JSONResponseMixin, generic.View):

    def post(self, request, *args, **kwargs):
        data = None
        password = request.POST.get('password')
        # if self.request.user.check_password(request.POST.get('password')) and \
        if password and \
            (
                self.request.user.groups.filter(name="Admin").exists() 
                or 
                (self.doc.get('reporter') and self.doc.get('reporter').get('id') == self.request.user.id)
                or 
                (self.doc.get('assignee') and self.doc.get('assignee').get('id') == self.request.user.id)
            ):

            category_password = get_last_category_password(self.doc["category"]["id"])
            if not category_password or not (category_password and check_password(password, category_password.password)):
                msg = _("You are not authorized to view this information.")
                messages.add_message(self.request, messages.ERROR, msg, extra_tags='danger')
            else:
                doc_id = request.POST.get('id')

                citizen = Pdata.objects.get(key=doc_id) if Pdata.objects.filter(key=doc_id).exists() else None
                # citizen = cryptocode.decrypt(citizen.data, doc_id) if citizen else None
                citizen = cryptography_fernet_decrypt(citizen.data, doc_id) if citizen else None

                contact = Cdata.objects.get(key=doc_id) if Cdata.objects.filter(key=doc_id).exists() else None
                # contact = cryptocode.decrypt(contact.data, doc_id) if contact else None
                contact = cryptography_fernet_decrypt(contact.data, doc_id) if contact else None

                data = {
                    'citizen': citizen,
                    'contact': contact,
                }

        else:
            msg = _("The password was not correct, we could not proceed with action.")
            messages.add_message(self.request, messages.ERROR, msg, extra_tags='danger')

        context = {
            'msg': render(self.request, 'common/messages.html').content.decode("utf-8"),
            'data': data
        }
        return self.render_to_json_response(context, safe=False)

class GetIssueDescriptionView(IssueMixin, AJAXRequestMixin, LoginRequiredMixin, JSONResponseMixin, generic.View):

    def post(self, request, *args, **kwargs):
        data = None

        try:
            password = request.POST.get('password')

            category_password = get_last_category_password(self.doc["category"]["id"])
            if not category_password or not (category_password and check_password(password, category_password.password)):
                raise PermissionDenied

            privacy_passwords = get_all_privacy_passwords(self.doc["category"]["id"])
            description_encrypt = self.doc['description']
            reasons = self.doc['reasons'] if 'reasons' in self.doc else []
            comments = self.doc['comments'] if 'comments' in self.doc else []
            
            for i_r in range(len(reasons)):
                if reasons[i_r].get('type') == 'comment' and reasons[i_r].get('comment') and "b'" in reasons[i_r].get('comment'):
                    for cat_pass in privacy_passwords:
                        try:
                            reasons[i_r]['comment'] = cryptography_fernet_decrypt(reasons[i_r]['comment'], cat_pass)
                            break
                        except:
                            pass
            for i_r in range(len(comments)):
                if comments[i_r].get('type') == 'comment' and comments[i_r].get('comment') and "b'" in comments[i_r].get('comment'):
                    for cat_pass in privacy_passwords:
                        try:
                            comments[i_r]['comment'] = cryptography_fernet_decrypt(comments[i_r]['comment'], cat_pass)
                            break
                        except:
                            pass
            data = dict()
            for cat_pass in privacy_passwords:
                try:
                    data['description'] = cryptography_fernet_decrypt(description_encrypt, cat_pass)
                    break
                except:
                    pass
            data['reasons'] = reasons
            data['comments'] = comments

        except:
            msg = _("The password was not correct, we could not proceed with action.")
            messages.add_message(self.request, messages.ERROR, msg, extra_tags='danger')

        context = {
            'msg': render(self.request, 'common/messages.html').content.decode("utf-8"),
            'data': data
        }
        return self.render_to_json_response(context, safe=False)
    

class IssueCommentDecryptListView(IssueMixin, IssueCommentsContextMixin, AJAXRequestMixin, LoginRequiredMixin,
                           generic.ListView):
    template_name = 'grm/issue_comments.html'
    context_object_name = 'comments'
    permissions = ('read',)

    def get_queryset(self):
        password = self.request.GET.get('password')
        category_password = get_last_category_password(self.doc["category"]["id"])
        if not category_password or not (category_password and check_password(password, category_password.password)):
            raise PermissionDenied
        
        comments = self.doc['comments'] if 'comments' in self.doc else list()
        for i_r in range(len(comments)):
            if comments[i_r].get('comment') and "b'" in comments[i_r].get('comment'):
                for cat_pass in get_all_privacy_passwords(self.doc["category"]["id"]):
                    try:
                        comments[i_r]['comment'] = cryptography_fernet_decrypt(comments[i_r]['comment'], cat_pass)
                        break
                    except InvalidToken:
                        pass
                    except:
                        pass
        return comments


class IssueReasonsDecryptListView(IssueMixin, IssueCommentsContextMixin, AJAXRequestMixin, LoginRequiredMixin,
                           generic.ListView):
    template_name = 'grm/issue_attachments_column2.html'
    context_object_name = 'reasons'
    permissions = ('read',)

    def get_queryset(self):
        password = self.request.GET.get('password')
        category_password = get_last_category_password(self.doc["category"]["id"])
        if not category_password or not (category_password and check_password(password, category_password.password)):
            raise PermissionDenied
        
        reasons = self.doc['reasons'] if 'reasons' in self.doc else list()
        for i_r in range(len(reasons)):
            if reasons[i_r].get('type') == 'comment' and reasons[i_r].get('comment') and "b'" in reasons[i_r].get('comment'):
                for cat_pass in get_all_privacy_passwords(self.doc["category"]["id"]):
                    try:
                        reasons[i_r]['comment'] = cryptography_fernet_decrypt(reasons[i_r]['comment'], cat_pass)
                        break
                    except InvalidToken:
                        pass
                    except:
                        pass
        return reasons
    
class GetOriginalDescriptionIssueDataView(IssueMixin, AJAXRequestMixin, LoginRequiredMixin, JSONResponseMixin, generic.View):

    def post(self, request, *args, **kwargs):
        data = None
        password = request.POST.get('password')
        category_password = get_last_category_password(self.doc["category"]["id"])
        if not category_password or not (category_password and check_password(password, category_password.password)):
            raise PermissionDenied
        
        for cat_pass in get_all_privacy_passwords(self.doc["category"]["id"]):
            try:
                data = {
                    'original_description': cryptography_fernet_decrypt(self.doc['original_description'], cat_pass)
                }
                break
            except:
                pass

        if not data:
            msg = _("The password was not correct, we could not proceed with action.")
            messages.add_message(self.request, messages.ERROR, msg, extra_tags='danger')

        context = {
            'msg': render(self.request, 'common/messages.html').content.decode("utf-8"),
            'data': data
        }
        return self.render_to_json_response(context, safe=False)