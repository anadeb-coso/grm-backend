import random
import uuid
from datetime import datetime, timedelta
import requests

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views import generic
from cryptography.fernet import InvalidToken
from django.contrib.auth.hashers import check_password

from authentication.models import Cdata, GovernmentWorker, Pdata, anonymize_issue_data, get_assignee, get_adl_to_escalate
from dashboard.grm.forms import CheckPasswordForm
from dashboard.forms.forms import FileForm
from dashboard.grm import CHOICE_CONTACT
from dashboard.grm.forms import (
    IssueCommentForm, IssueDetailsForm, IssueRejectReasonForm, IssueResearchResultForm, MAX_LENGTH, NewIssueConfirmForm,
    NewIssueContactForm, NewIssueDetailsForm, NewIssueLocationForm, NewIssuePersonForm, SearchIssueForm,
    IssueOpenStatusForm, IssueReasonCommentForm, IssueIssueEscalateForm, IssueSetUnresolvedForm,
    IssueIssuePublishForm, IssueIssueUnpublishForm, IssueCategoryForm
)
from dashboard.grm.serializers import LegacyIssueDoc
from dashboard.mixins import AJAXRequestMixin, JSONResponseMixin, ModalFormMixin, PageMixin
from grm.utils import (
    get_administrative_level_descendants_using_mis, get_auto_increment_id_using_postgres,
    get_child_administrative_regions_using_mis, get_parent_administrative_level_using_mis,
    cryptography_fernet_encrypt, cryptography_fernet_decrypt,
)
from dashboard.grm.functions import send_assignee_notification_by_mail
from dashboard.tasks import (
    check_issues, send_sms_message, escalate_issues, send_a_new_issue_notification,
    send_issue_status_notifications,
)
from authentication.permissions import AdminPermissionRequiredMixin
from privacy.functions import get_last_category_password, get_all_privacy_passwords
from issue.models import (
    Issue, IssueAgeGroup, IssueCategory, IssueCitizenGroup1, IssueCitizenGroup2, IssueDepartment,
    IssueStatus, IssueType, Wave,
)
from grm.call_objects_from_other_db import mis_objects_call
from administrativelevels.models import AdministrativeLevel, CVD


ISSUE_PREFETCH_RELATED = (
    'comments', 'reasons', 'reasons__attachment', 'escalation_reasons', 'escalation_reasons__attachment',
    'escalation_levels', 'issue_status_stories', 'issue_status_stories__status', 'issue_status_stories__user',
    'attachments',
)
ISSUE_SELECT_RELATED = ('status', 'category', 'age_group', 'issue_type')


def _get_issue_department(department_id):
    """`department_id` provient de `category.assigned_department['id']` (JSONField, cf.
    issue/models.py::IssueCategory) — remplace l'ancienne requête Mango
    `grm_db.get_query_result({"id": department_id, "type": "issue_department"})`."""
    return IssueDepartment.objects.filter(legacy_id=department_id).first()


class IssueCommentsContextMixin:
    doc_department = None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        try:
            assigned_department = self.doc['category']['assigned_department']
            department_id = assigned_department.get('id') if isinstance(assigned_department, dict) else assigned_department
            department = _get_issue_department(department_id)
            self.doc_department = {'head': {'id': department.head_id, 'name': department.head_name}} if department else {'head': {'id': None}}
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
        send_issue_status_notifications()
        return super().dispatch(request, *args, **kwargs)


class StartNewIssueView(LoginRequiredMixin, generic.View):

    def post(self, request, *args, **kwargs):
        auto_increment_id = get_auto_increment_id_using_postgres()
        user = request.user
        sample_words = ["Tree", "Cat", "Dog", "Car", "House"]
        now = timezone.now()
        # Brouillon minimal (status/category/issue_type/administrative_region encore nuls, cf.
        # issue/models.py) rempli progressivement par le wizard new_issue_step_1..6.
        issue = Issue.objects.create(
            auto_increment_id=auto_increment_id,
            internal_code=f'DRAFT-{auto_increment_id}-{uuid.uuid4().hex[:8]}',
            description='',
            confirmed=False,
            escalate_flag=False,
            reporter_id=user.id,
            reporter_name=user.name,
            assignee_id=user.id,
            assignee_name=user.name,
            created_date=now,
            intake_date=now,
            issue_date=now,
            tracking_code=f'{random.choice(sample_words)}{random.choice(range(1, 1000))}',
        )
        return HttpResponseRedirect(
            reverse('dashboard:grm:new_issue_step_1', kwargs={'issue': issue.auto_increment_id}))


class IssueMixin:
    doc = None
    max_attachments = 20
    permissions = ('read', 'write')
    has_permission = True

    def get_issue_queryset(self, **kwargs):
        return Issue.objects.select_related(*ISSUE_SELECT_RELATED).prefetch_related(*ISSUE_PREFETCH_RELATED).filter(
            auto_increment_id=kwargs['issue'],
        )

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
                            if not user.governmentworker.has_read_permission_for_issue(self.doc.issue):
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
        try:
            issue = self.get_issue_queryset(**kwargs).get()
        except Issue.DoesNotExist:
            raise Http404
        self.doc = LegacyIssueDoc(issue)

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
        permission_to_edit = False
        if user.groups.filter(name="Admin").exists():
            permission_to_edit = True
        elif hasattr(user, 'governmentworker') and self.doc and "administrative_region" in self.doc and "administrative_id" in self.doc["administrative_region"]:
            parents_id = user.governmentworker.all_administrative_ids
            descendants = []
            for _id in parents_id:
                descendants += get_administrative_level_descendants_using_mis(None, _id, [], self.request.user)
            allowed_regions = descendants + parents_id

            if self.doc["administrative_region"]["administrative_id"] in allowed_regions:
                permission_to_edit = True

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
            issue_password_file = data['issue_password_file'] or self.request.session["issue_password"]
            file = data['file']
            _ok = True
            
            category_id = int(data['category_id'] if 'category_id' in data and data['category_id'] else (self.doc['category']["id"] if 'category' in self.doc and isinstance(self.doc['category'], dict) else 0))
            
            if ((category_id in (4, 7)) or not self.doc.get('category')) and issue_password_file:
                last_category_password = get_last_category_password(category_id)
                if not last_category_password:
                    msg = _("The file has not been saved. No password is defined for this category of complaint.")
                    messages.add_message(self.request, messages.ERROR, msg, extra_tags='error')
                    _ok = False
                elif not check_password(issue_password_file, last_category_password.password):
                    msg = _("The file has not been saved. The password does not match.")
                    messages.add_message(self.request, messages.ERROR, msg, extra_tags='error')
                    _ok = False
                else:
                    file = cryptography_fernet_encrypt(file, issue_password_file, _type="file", filename=file.name)
                    file.name = f'encrypt_{file.name}' if 'encrypt_' not in file.name else file.name

            if _ok:
                self.doc.add_attachment(file, subject='reason' if reason else None, user=self.request.user)
                msg = _("The attachment was successfully uploaded.")
                messages.add_message(self.request, messages.SUCCESS, msg, extra_tags='success')
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
        self.specific_permissions()

        from issue.models import Attachment, Reason

        # `kwargs['attachment']` correspond désormais au pk réel (UUID) de l'Attachment ou du
        # Reason concerné (cf. dashboard/grm/serializers.py::_attachment_to_legacy/_reason_to_legacy).
        target_id = kwargs['attachment']

        # Tombstone logique (`is_deleted=True` + `updated_at` explicite), PAS de suppression
        # physique : `Attachment`/`Reason` sont synchronisés vers le mobile (cf.
        # grm.models_base.TimestampedSyncModel) — un `.delete()` fait disparaître la ligne AVANT
        # que le pull incrémental n'ait pu calculer un tombstone à partir d'elle, laissant le
        # fichier/la raison visible indéfiniment côté mobile malgré sa suppression ici. Le fichier
        # physique (S3/storage) reste volontairement en place : purgé plus tard par
        # issue.tasks.cleanup_old_tombstones, une fois la suppression sûrement vue par tous les
        # appareils.
        now = timezone.now()
        Attachment.objects.filter(pk=target_id, issue=self.doc.issue).update(is_deleted=True, updated_at=now)
        Reason.objects.filter(pk=target_id, issue=self.doc.issue).update(is_deleted=True, updated_at=now)

        self.doc.refresh()
        msg = _("The attachment was successfully deleted.")
        messages.add_message(self.request, messages.SUCCESS, msg, extra_tags='success')
        context = {'msg': render(self.request, 'common/messages.html').content.decode("utf-8")}
        return self.render_to_json_response(context, safe=False)


class IssueAttachmentDecryptView(IssueMixin, ModalFormMixin, LoginRequiredMixin,
                                generic.DeleteView):

    def get(self, request, *args, **kwargs):
        self.specific_permissions()

        password = request.GET.get('password') or self.request.session["issue_password"]

        if not password:
            raise Http404
        else:
            category_password = get_last_category_password(self.doc["category"]["id"])
            if not category_password or not (category_password and check_password(password, category_password.password)):
                raise PermissionDenied

        from issue.models import Attachment, Reason

        target_id = kwargs['attachment']
        attachment = Attachment.objects.filter(pk=target_id, issue=self.doc.issue).first()
        attachment_name = None
        attachment_content = None

        if attachment is None:
            reason = Reason.objects.filter(pk=target_id, issue=self.doc.issue).select_related('attachment').first()
            if reason and reason.attachment_id:
                attachment = reason.attachment

        if attachment is not None and attachment.file:
            attachment_name = attachment.file_name
            # attachment.file.open('rb')
            # try:
            #     attachment_content = attachment.file.read()
            # finally:
            #     attachment.file.close()
            try:
                r = requests.get(attachment.file.url.split('?')[0], stream=True)
                r.raise_for_status()
                attachment_content = r.content
            except Exception:
                pass

        if not attachment_name or attachment_content is None:
            raise Http404

        for cat_pass in get_all_privacy_passwords(self.doc["category"]["id"]):
            try:
                return cryptography_fernet_decrypt(attachment_content, cat_pass, _type="file", filename=attachment_name)
            except Exception:
                pass

        raise PermissionDenied


class IssueAttachmentListView(IssueMixin, IssueCommentsContextMixin, AJAXRequestMixin, LoginRequiredMixin, generic.ListView):
    template_name = 'grm/issue_attachments.html'
    context_object_name = 'attachments'

    def get_queryset(self):
        attr = self.request.GET.get('attr', 'attachments')
        if attr != 'attachments':
            self.context_object_name = attr
        return self.doc[attr] if attr in self.doc else list()

    def dispatch(self, request, *args, **kwargs):
        column = self.request.GET.get('column', '')
        if column:
            self.template_name = 'grm/issue_attachments{}.html'.format(('_column'+column) if column else '')
        return super().dispatch(request, *args, **kwargs)


class IssueFormMixin(IssueMixin, generic.FormView):

    def get_form_kwargs(self):
        self.initial = {'doc': self.doc, 'user': self.request.user}
        return super().get_form_kwargs()


class NewIssueMixin(LoginRequiredMixin, IssueFormMixin):
    fields_to_check = None

    def dispatch(self, request, *args, **kwargs):
        dispatch = super().dispatch(request, *args, **kwargs)
        if not self.has_required_fields():
            raise Http404
        return dispatch

    def get_issue_queryset(self, **kwargs):
        return Issue.objects.select_related(*ISSUE_SELECT_RELATED).prefetch_related(*ISSUE_PREFETCH_RELATED).filter(
            auto_increment_id=kwargs['issue'], reporter_id=self.request.user.id, confirmed=False,
        )

    def get_form_kwargs(self):
        self.initial = {'doc': self.doc}
        return super().get_form_kwargs()

    # Champs booléens dont la valeur `False` est un choix explicite valide, pas un signe que
    # l'étape correspondante du wizard n'a pas encore été complétée (contrairement à CouchDB, la
    # colonne Postgres a de toute façon un défaut `False` — la distinction "jamais renseigné" vs
    # "renseigné à False" n'existe plus au niveau du dict, cf. has_required_fields ci-dessous).
    BOOLEAN_FIELDS_NOT_GATED = {'ongoing_issue', 'event_recurrence'}

    def has_required_fields(self):
        # `issue_to_legacy_dict` inclut toujours toutes les clés (valeur `None`/'' par défaut) —
        # contrairement à un document CouchDB où une clé jamais définie est simplement absente.
        # Le test doit donc porter sur la valeur (falsy = pas encore renseigné), pas sur la seule
        # présence de la clé, pour que le wizard bloque toujours la progression tant qu'une étape
        # précédente n'a pas été complétée (bug trouvé lors de la vérification de cette migration).
        if self.fields_to_check and self.doc:
            for field in self.fields_to_check:
                if field in self.BOOLEAN_FIELDS_NOT_GATED:
                    continue
                if not self.doc.get(field):
                    return False
        return True

    def set_details_fields(self, data):
        self.doc['intake_date'] = data['intake_date']
        self.doc['issue_date'] = data['issue_date']

        if int(data['category']) in (4, 7) and data.get("issue_password"):
            self.request.session["issue_password"] = data.get("issue_password")
        if int(data['category']) in (4, 7) and self.request.POST.get("confirm") == "confirm":
            self.doc['description'] = str(cryptography_fernet_encrypt(data['description'], self.request.session["issue_password"]))
        else:
            self.doc['description'] = data['description']
        self.doc['publish'] = False

        doc_category = IssueCategory.objects.filter(legacy_id=int(data['category'])).first()
        if not doc_category:
            raise Http404
        department_id = doc_category.assigned_department.get('id') if isinstance(doc_category.assigned_department, dict) else doc_category.assigned_department

        self.doc['issue_type'] = {"id": 1, "name": "Plainte"}
        assigned_department_level = (
            doc_category.assigned_department.get('administrative_level')
            if isinstance(doc_category.assigned_department, dict) else None
        )
        self.doc['category'] = {
            "id": doc_category.legacy_id,
            "name": doc_category.name,
            "confidentiality_level": doc_category.confidentiality_level,
            "assigned_department": department_id,
            "administrative_level": assigned_department_level,
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
            doc_issue_age_group = IssueAgeGroup.objects.filter(legacy_id=int(data['citizen_age_group'])).first()
            if not doc_issue_age_group:
                raise Http404
            self.doc['citizen_age_group'] = {"name": doc_issue_age_group.name, "id": doc_issue_age_group.legacy_id}
        else:
            self.doc['citizen_age_group'] = ""

        if data.get('citizen_group_1'):
            doc_issue_citizen_group_1 = IssueCitizenGroup1.objects.filter(legacy_id=int(data['citizen_group_1'])).first()
            if not doc_issue_citizen_group_1:
                raise Http404
            self.doc['citizen_group_1'] = {"name": doc_issue_citizen_group_1.name, "id": doc_issue_citizen_group_1.legacy_id}
        else:
            self.doc['citizen_group_1'] = ""

        if data.get('citizen_group_2'):
            doc_issue_citizen_group_2 = IssueCitizenGroup2.objects.filter(legacy_id=int(data['citizen_group_2'])).first()
            if not doc_issue_citizen_group_2:
                raise Http404
            self.doc['citizen_group_2'] = {"name": doc_issue_citizen_group_2.name, "id": doc_issue_citizen_group_2.legacy_id}
        else:
            self.doc['citizen_group_2'] = ""

        self.doc['citizen_or_group'] = data['citizen_or_group']

    def set_location_fields(self, data):
        administrative_id = data['administrative_region_value']
        region = mis_objects_call.filter_objects(AdministrativeLevel, id=int(administrative_id)).first() if administrative_id else None
        if not region:
            raise Http404

        self.doc['administrative_region'] = {
            "administrative_id": str(region.id),
            "name": region.name,
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
        assignee = get_assignee(self.doc.issue)

        if not assignee:
            msg = _("No staff member is designated to handle this issue. Please report it to the relevant department.")
            messages.add_message(self.request, messages.ERROR, msg, extra_tags='danger')

        self.doc['assignee'] = assignee if assignee else ''

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
        self.set_contact_fields(data)
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
        self.set_person_fields(data)
        self.doc.save()
        return HttpResponseRedirect(reverse('dashboard:grm:new_issue_step_3', kwargs={'issue': self.kwargs['issue']}))


class NewIssueDetailsFormView(PageMixin, NewIssueMixin):
    template_name = 'grm/new_issue_details.html'
    title = _('GRM')
    active_level1 = 'grm'
    form_class = NewIssueDetailsForm
    fields_to_check = set() #('contact_medium', 'citizen')

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
                       'category', 'description',
                       'ongoing_issue', 'event_recurrence')

    def form_valid(self, form):
        data = form.cleaned_data
        self.set_location_fields(data)

        self.set_assignee()

        self.doc.save()
        # if not self.doc['assignee']:
        #     return HttpResponseRedirect(
        #         reverse('dashboard:grm:new_issue_step_4', kwargs={'issue': self.kwargs['issue']}))
        return HttpResponseRedirect(reverse('dashboard:grm:new_issue_step_5', kwargs={'issue': self.kwargs['issue']}))


class NewIssueConfirmFormView(PageMixin, NewIssueMixin):
    template_name = 'grm/new_issue_confirm.html'
    title = _('GRM')
    active_level1 = 'grm'
    form_class = NewIssueConfirmForm
    fields_to_check = ('contact_medium', 'intake_date', 'issue_date',
                       'category', 'description',
                       'ongoing_issue', 'event_recurrence', 'administrative_region') #'assignee', 

    def form_valid(self, form):
        data = form.cleaned_data
        self.set_contact_fields(data)
        self.set_person_fields(data)
        self.set_details_fields(data)
        self.set_location_fields(data)
        self.set_assignee()

        # if not self.doc['assignee']:
        #     return HttpResponseRedirect(
        #         reverse('dashboard:grm:new_issue_step_5', kwargs={'issue': self.kwargs['issue']}))

        self.set_contact_fields(data)
        doc_category = IssueCategory.objects.filter(legacy_id=self.doc['category']['id']).first()
        if not doc_category:
            raise Http404
        administrative_id = self.doc["administrative_region"]["administrative_id"]
        self.doc['internal_code'] = f'{doc_category.abbreviation}-{administrative_id}-{self.doc["auto_increment_id"]}'

        doc_status = IssueStatus.objects.filter(initial_status=True).first()
        if not doc_status:
            raise Http404
        self.doc['status'] = {"name": doc_status.name, "id": doc_status.legacy_id}

        self.doc['created_date'] = timezone.now()
        self.doc['confirmed'] = True
        self.doc['source'] = "web"
        self.doc.save()

        anonymize_issue_data(self.doc)
        self.doc.save()

        # `confirmed=True` n'est persisté qu'à l'instant précédent : la notification doit être
        # envoyée après coup, sinon le filtre `confirmed=True` de la tâche l'ignore silencieusement
        # (bug trouvé lors de la vérification de la procédure de gestion des plaintes §2 — la
        # notification n'était alors envoyée que par accident, à la prochaine ouverture du
        # dashboard par un autre utilisateur).
        try:
            send_a_new_issue_notification()
        except Exception:
            pass

        self.request.session["issue_password"] = None
        return HttpResponseRedirect(reverse('dashboard:grm:new_issue_step_6', kwargs={'issue': self.kwargs['issue']}))


class NewIssueConfirmationFormView(PageMixin, NewIssueMixin):
    template_name = 'grm/new_issue_confirmation.html'
    title = _('GRM')
    active_level1 = 'grm'
    form_class = NewIssueConfirmForm
    permissions = ('read_only_by_reporter',)

    def get_issue_queryset(self, **kwargs):
        return Issue.objects.select_related(*ISSUE_SELECT_RELATED).prefetch_related(*ISSUE_PREFETCH_RELATED).filter(
            auto_increment_id=kwargs['issue'], confirmed=True,
        )


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
        send_issue_status_notifications()
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        context['publish_option'] = False
        context['breadcrumb'] = False

        context['all_total_issues'] = Issue.objects.filter(confirmed=True, is_deleted=False).count()

        if user.groups.filter().exists():
            context['publish_option'] = True
        return context


class IssueListView(AJAXRequestMixin, LoginRequiredMixin, generic.ListView):
    template_name = 'grm/issue_list.html'
    context_object_name = 'issues'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        index = int(self.request.GET.get('index'))
        offset = int(self.request.GET.get('offset'))
        issues, wave_administrative_ids = self.get_results()
        issues = list(issues)
        context['total_issues'] = len(issues)

        context['issues'] = issues if self.request.GET.get('see_all') in (True, 'true') else issues[index:index + offset]

        context['wave_administrative_levels'] = mis_objects_call.filter_objects(
            CVD, headquarters_village__id__in=wave_administrative_ids
        )
        context['total_cvds_total_villages_message'] = _("%(total_cvds)d CVDs, including %(total_villages)d villages") % {
            'total_cvds': context['wave_administrative_levels'].count(),
            'total_villages': len(wave_administrative_ids)
        }

        # Simplification (cf. décision utilisateur, migration dashboard web) : les widgets
        # "facilitateurs par village" reposaient sur une jointure ad-hoc avec des vues CouchDB
        # `eadls` (administrative_regions_objects[].villages[]) sans équivalent dans le modèle
        # Postgres `Adl` actuel. On ne les recalcule plus ici — laissés vides plutôt que de
        # reproduire fidèlement un algorithme bespoke non vérifiable sans navigateur.
        context['wave_administrative_levels_with_facilitators'] = {}
        context['wave_administrative_levels_with_adl_profile'] = {}

        # Comptage des issues par région administrative (remplace la boucle Python sur les docs
        # CouchDB) — inchangé dans son résultat, juste calculé sur des instances Issue Postgres.
        region_stats_wave = {}
        region_stats_wave_for_cvd = {}

        def fill_count(key, stats: dict, name=None):
            key = str(key)
            if key in stats:
                stats[key]['count'] = stats[key]['count'] + 1
            else:
                stats[key] = {'count': 1}
            if name:
                stats[key]['name'] = name

        def process_stats(stats: dict):
            for k in stats:
                k = str(k)
                stats[k]['percentage'] = round(stats[k]['count'] * 100 / context['total_issues']) if context['total_issues'] else 0
                stats[k]['issues'] = stats[k]['count']

        if wave_administrative_ids:
            for doc in issues:
                if doc.get('administrative_region') and doc['administrative_region'].get('administrative_id'):
                    fill_count(doc['administrative_region']['administrative_id'], region_stats_wave)

        for _cvd in context['wave_administrative_levels']:
            cvd_villages_id = list(_cvd.get_villages().values_list('id', flat=True))
            region_stats_wave_for_cvd[str(_cvd.id)] = {'count': sum([region_stats_wave[str(k)]['count'] for k in cvd_villages_id if str(k) in region_stats_wave])}

        process_stats(region_stats_wave_for_cvd)

        context['region_stats_wave_for_cvd'] = dict(
            sorted(region_stats_wave_for_cvd.items(), key=lambda item: item[1]['count'], reverse=True)
        )

        return context

    def get_queryset(self):
        return []

    def get_results(self):
        from dashboard.grm.functions import build_issue_queryset
        index = int(self.request.GET.get('index'))
        offset = int(self.request.GET.get('offset'))
        queryset, wave_administrative_ids = build_issue_queryset(self.request)
        docs = [LegacyIssueDoc(issue) for issue in queryset]
        return docs, wave_administrative_ids


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
        self.initial = {'doc': self.doc}
        return super().get_form_kwargs()

    def get_issue_queryset(self, **kwargs):
        return Issue.objects.select_related(*ISSUE_SELECT_RELATED).prefetch_related(*ISSUE_PREFETCH_RELATED).filter(
            auto_increment_id=kwargs['issue'],
        )

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
            parent_ids = user.governmentworker.all_administrative_ids
            descendants = []
            for _id in parent_ids:
                descendants += get_administrative_level_descendants_using_mis(None, _id, [], self.request.user)
            allowed_regions = descendants + parent_ids

            if self.doc["administrative_region"]["administrative_id"] in allowed_regions:
                context['enable_add_comment'] = True

        context['comment_form'] = IssueCommentForm()
        context['reason_comment_form'] = IssueReasonCommentForm()
        context['doc_status'] = self.doc['status']
        context['password_confirm_form'] = CheckPasswordForm()
        context['category_form'] = IssueCategoryForm(
            initial={'doc': self.doc, 'user': self.request.user}
        )

        escalate_issues()
        send_a_new_issue_notification()
        send_issue_status_notifications()

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

        send_assignee_notification_by_mail(self.doc, worker.user)

        msg = _("The issue was successfully edited.")
        messages.add_message(self.request, messages.SUCCESS, msg, extra_tags='success')
        context = {'msg': render(self.request, 'common/messages.html').content.decode("utf-8")}
        return self.render_to_json_response(context, safe=False)


class EditIssueCategoryView(IssueMixin, AJAXRequestMixin, AdminPermissionRequiredMixin, JSONResponseMixin, generic.View):
    permissions = ('read',)

    def post(self, request, *args, **kwargs):
        category_id = int(request.POST.get('category_id'))

        doc_category = IssueCategory.objects.filter(legacy_id=category_id).first()
        if not doc_category:
            raise Http404
        department_id = doc_category.assigned_department.get('id') if isinstance(doc_category.assigned_department, dict) else doc_category.assigned_department

        _comment = f'{_("Category change")} : "{self.doc["category"]["name"]}" {_("to")} "{doc_category.name}"'
        try:
            doc_status = IssueStatus.objects.filter(name=self.doc['status']['name']).first()
            self.doc.add_status_story({"id": doc_status.legacy_id, "name": doc_status.name}, _comment, user=self.request.user)
        except:
            pass

        self.doc.add_comment(
            _comment,
            user=self.request.user,
        )

        assigned_department_level = (
            doc_category.assigned_department.get('administrative_level')
            if isinstance(doc_category.assigned_department, dict) else None
        )
        self.doc['category'] = {
            "id": doc_category.legacy_id,
            "name": doc_category.name,
            "confidentiality_level": doc_category.confidentiality_level,
            "assigned_department": department_id,
            "administrative_level": assigned_department_level,
        }

        self.doc.save()
        msg = _("The issue was successfully edited.")
        messages.add_message(self.request, messages.SUCCESS, msg, extra_tags='success')
        context = {'msg': render(self.request, 'common/messages.html').content.decode("utf-8")}
        return self.render_to_json_response(context, safe=False)


class AddCommentToIssueView(IssueMixin, AJAXRequestMixin, LoginRequiredMixin, JSONResponseMixin, generic.View):

    def post(self, request, *args, **kwargs):
        assigned_department = self.doc['category']['assigned_department']
        department_id = assigned_department.get('id') if isinstance(assigned_department, dict) else assigned_department
        doc_department = _get_issue_department(department_id)
        if not doc_department:
            raise Http404
        user_id = request.user.id
        if (self.doc['assignee'] and user_id != self.doc['assignee']['id'] and user_id != doc_department.head_id) and not request.user.groups.filter(name__in=["Admin", "Commentator", "Safeguard"]).exists():
            raise PermissionDenied()

        reason = self.request.GET.get('reason', '')

        comment = request.POST.get('comment').strip()

        if not reason:
            comment = comment[:MAX_LENGTH]

        _ok = True
        if comment:
            issue_password = request.POST.get('issue_password_reason') if request.POST.get('issue_password_reason') else request.POST.get('issue_password_comment')

            if self.doc['category']["id"] in (4, 7):
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
                if reason:
                    try:
                        doc_status = IssueStatus.objects.filter(name=self.doc['status']['name']).first()
                        self.doc.add_status_story({"id": doc_status.legacy_id, "name": doc_status.name}, comment, user=self.request.user)
                    except:
                        pass
                    self.doc.add_reason(subject='comment', comment=comment, user=request.user)
                else:
                    self.doc.add_comment(comment, user=request.user)
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
        context['doc_status'] = self.doc['status']

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
            except Exception:
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
        # Accepter une plainte "Enregistrée" ou la rouvrir depuis un statut terminal (Résolue /
        # Rejetée / Non résolue) est réservé à l'agent assigné ou à un administrateur (procédure
        # de gestion des plaintes §3/§8) — ce n'était auparavant qu'une contrainte d'affichage
        # (bouton désactivé côté template), pas une vérification serveur.
        super().check_permissions()
        if not self.has_permission:
            return
        user = self.request.user
        is_admin = user.groups.filter(name="Admin").exists()
        is_assignee = bool(self.doc.get('assignee')) and self.doc['assignee'].get('id') == user.id
        if not (is_admin or is_assignee):
            self.has_permission = False

    def form_valid(self, form):
        data = form.cleaned_data

        doc_status = IssueStatus.objects.filter(open_status=True).first()
        if not doc_status:
            raise Http404
        self.doc['status'] = {"name": doc_status.name, "id": doc_status.legacy_id}
        self.doc.save()

        self.doc.add_status_story({"id": doc_status.legacy_id, "name": doc_status.name}, (_("The issue was reopened") if self.doc.issue.issue_status_stories.exists() else _("The issue was accepted")) + (f' [{data["open_reason"]}]' if data["open_reason"] else ""), user=self.request.user)
        self.doc.add_comment(data["open_reason"] if data["open_reason"] else (_("The issue was reopened") if self.doc.issue.issue_status_stories.exists() else _("The issue was accepted")), user=self.request.user)
        send_issue_status_notifications()

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

    def form_valid(self, form):
        data = form.cleaned_data
        issue_password = data['issue_password'] if 'issue_password' in data else None
        _ok = True
        _comment = data["research_result"]
        if self.doc['category']["id"] in (4, 7):
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

            doc_status = IssueStatus.objects.filter(final_status=True).first()
            if not doc_status:
                raise Http404
            self.doc['status'] = {"name": doc_status.name, "id": doc_status.legacy_id}
            self.doc['resolution_date'] = timezone.now()
            self.doc.save()

            self.doc.add_status_story({"id": doc_status.legacy_id, "name": doc_status.name}, _("The issue was resolved") + (f' [{_comment}]' if _comment else ""), user=self.request.user)
            self.doc.add_comment(_comment, user=self.request.user)
            self.doc.add_reason(subject='comment', comment=_comment, user=self.request.user)

            file = data['file_pdf']
            if file and self.doc.get('category') and self.doc['category']["id"] in (4, 7) and issue_password:
                file = cryptography_fernet_encrypt(file, issue_password, _type="file", filename=file.name)
                file.name = f'encrypt_{file.name}' if 'encrypt_' not in file.name else file.name

            if file:
                self.doc.add_attachment(file, subject='resolution', user=self.request.user)

            send_issue_status_notifications()

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

    def form_valid(self, form):
        data = form.cleaned_data

        doc_status = IssueStatus.objects.filter(unresolved_status=True).first()
        if not doc_status:
            raise Http404
        self.doc['status'] = {"name": doc_status.name, "id": doc_status.legacy_id}
        self.doc.save()

        self.doc.add_status_story({"id": doc_status.legacy_id, "name": doc_status.name}, _("The issue wasn't resolved") + (f' [{data["unresolved_reason"]}]' if data["unresolved_reason"] else ""), user=self.request.user)
        self.doc.add_comment(data["unresolved_reason"], user=self.request.user)
        send_issue_status_notifications()
        self.doc.add_reason(subject='comment', comment=data["unresolved_reason"], user=self.request.user)

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

    def form_valid(self, form):
        data = form.cleaned_data
        issue_password = data['issue_password'] if 'issue_password' in data else None
        _ok = True
        _comment = data["escalate_reason"]
        if self.doc['category']["id"] in (4, 7):
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
            self.doc['escalate_flag'] = True
            self.doc.save()

            try:
                doc_status = IssueStatus.objects.filter(name=self.doc['status']['name']).first()
                self.doc.add_status_story({"id": doc_status.legacy_id, "name": doc_status.name}, _("The issue was escalated") + (f" [{_comment}]" if _comment else ""), user=self.request.user)
            except:
                pass
            self.doc.add_comment(_comment, user=self.request.user)

            file = data['file_pdf']
            if file and self.doc.get('category') and self.doc['category']["id"] in (4, 7) and issue_password:
                file = cryptography_fernet_encrypt(file, issue_password, _type="file", filename=file.name)
                file.name = f'encrypt_{file.name}' if 'encrypt_' not in file.name else file.name

            attachment = None
            if file:
                attachment = self.doc.add_attachment(file, subject='escalation', user=self.request.user)

            self.doc.add_escalation_reason(_comment, user=self.request.user, attachment=attachment)

            # Résout immédiatement le niveau administratif cible (l'ancien code CouchDB laissait
            # ce calcul à la tâche Celery asynchrone `escalate_issues` ; `get_adl_to_escalate`
            # (authentication/models.py, Phase 0) est une requête Postgres/mis peu coûteuse, donc
            # plus besoin de différer ce travail). Part du dernier niveau d'escalade connu, sinon
            # de la région d'origine de l'issue.
            current_level = self.doc.issue.escalation_levels.order_by('-created_at').first()
            
            base_administrative_id = (
                current_level.administrative_id if current_level and current_level.administrative_id
                else self.doc.issue.administrative_region_id
            )
            
            escalate_to = get_adl_to_escalate(base_administrative_id) if base_administrative_id else None
            
            if escalate_to:
                self.doc.add_escalation_level(
                    administrative_level=escalate_to['administrative_level'],
                    administrative_id=escalate_to['administrative_id'],
                    name=escalate_to['name'],
                )
            self.doc.save()

            escalate_issues()
            send_issue_status_notifications()

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
        # Publier une plainte est le rôle du spécialiste sauvegarde désigné (procédure de gestion
        # des plaintes §2, ex. "KEGBAO"), pas seulement de l'Admin — le groupe "Safeguard" existe
        # déjà et est utilisé ailleurs (cf. AddCommentToIssueView) pour ce même rôle.
        self.has_permission = False
        if self.request.user.groups.filter(name__in=["Admin", "Safeguard"]).exists():
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
                # Republication : l'ancien code CouchDB conservait un historique de descriptions
                # sous des clés dynamiques `description_<timestamp>` sans équivalent Postgres —
                # simplification documentée (cf. dashboard/grm/serializers.py::_IGNORED_ON_SAVE) :
                # seule la dernière `original_description` est conservée.
                if self.doc['category']["id"] in (4, 7):
                    self.doc['original_description'] = self.doc.get('description')
                    self.doc['description'] = str(cryptography_fernet_encrypt(data["issue_description"], issue_password))
                else:
                    self.doc['original_description'] = str(cryptography_fernet_encrypt(self.doc.get('description'), issue_password))
                    self.doc['description'] = data["issue_description"]

            self.doc['publish'] = True
            self.doc['publish_date'] = timezone.now()

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
        if self.request.user.groups.filter(name__in=["Admin", "Safeguard"]).exists():
            self.has_permission = True

    def form_valid(self, form):
        self.doc['publish'] = False
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

    def form_valid(self, form):
        data = form.cleaned_data

        doc_status = IssueStatus.objects.filter(rejected_status=True).first()
        if not doc_status:
            raise Http404
        self.doc['status'] = {"name": doc_status.name, "id": doc_status.legacy_id}
        self.doc['reject_date'] = timezone.now()
        self.doc.save()

        self.doc.add_status_story({"id": doc_status.legacy_id, "name": doc_status.name}, _("The issue was rejected") + (f' [{data["reject_reason"]}]' if data["reject_reason"] else ""), user=self.request.user)
        self.doc.add_comment(data["reject_reason"], user=self.request.user)
        send_issue_status_notifications()

        msg = _("The issue status was successfully updated.")
        messages.add_message(self.request, messages.SUCCESS, msg, extra_tags='success')

        context = {'msg': render(self.request, 'common/messages.html').content.decode("utf-8")}
        return self.render_to_json_response(context, safe=False)


class GetChoicesForNextAdministrativeLevelView(AJAXRequestMixin, LoginRequiredMixin, JSONResponseMixin, generic.View):
    def get(self, request, *args, **kwargs):
        parent_id = request.GET.get('parent_id')
        exclude_lower_level = request.GET.get('exclude_lower_level', None)
        data = get_child_administrative_regions_using_mis(None, parent_id, request.user)

        if data and exclude_lower_level and not get_child_administrative_regions_using_mis(None, data[0]['administrative_id'], request.user):
            data = []

        return self.render_to_json_response(data, safe=False)


class GetAncestorAdministrativeLevelsView(AJAXRequestMixin, LoginRequiredMixin, JSONResponseMixin, generic.View):
    def get(self, request, *args, **kwargs):
        administrative_id = request.GET.get('administrative_id', None)
        ancestors = []
        if administrative_id:
            has_parent = True
            while has_parent:
                parent = get_parent_administrative_level_using_mis(administrative_id)
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
                doc_id = self.doc['_id']

                citizen = Pdata.objects.get(key=doc_id) if Pdata.objects.filter(key=doc_id).exists() else None
                citizen = cryptography_fernet_decrypt(citizen.data, doc_id) if citizen else None

                contact = Cdata.objects.get(key=doc_id) if Cdata.objects.filter(key=doc_id).exists() else None
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
                        except Exception:
                            pass
            for i_r in range(len(comments)):
                if comments[i_r].get('comment') and "b'" in comments[i_r].get('comment'):
                    for cat_pass in privacy_passwords:
                        try:
                            comments[i_r]['comment'] = cryptography_fernet_decrypt(comments[i_r]['comment'], cat_pass)
                            break
                        except Exception:
                            pass
            data = dict()
            for cat_pass in privacy_passwords:
                try:
                    data['description'] = cryptography_fernet_decrypt(description_encrypt, cat_pass)
                    break
                except Exception:
                    pass
            data['reasons'] = reasons
            data['comments'] = comments

        except Exception:
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
                    except Exception:
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
                    except Exception:
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
            except Exception:
                pass

        if not data:
            msg = _("The password was not correct, we could not proceed with action.")
            messages.add_message(self.request, messages.ERROR, msg, extra_tags='danger')

        context = {
            'msg': render(self.request, 'common/messages.html').content.decode("utf-8"),
            'data': data
        }
        return self.render_to_json_response(context, safe=False)
