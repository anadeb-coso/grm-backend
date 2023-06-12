from django import forms
from django.conf import settings
from django.utils.translation import gettext_lazy as _

from authentication.models import get_government_worker_choices
from client import get_db
from dashboard.forms.widgets import RadioSelect
from dashboard.grm import CHOICE_CONTACT, CITIZEN_TYPE_CHOICES, CONTACT_CHOICES, GENDER_CHOICES, MEDIUM_CHOICES
from grm.utils import (
    get_administrative_region_choices, get_base_administrative_id, get_administrative_regions_by_level,
    get_issue_age_group_choices, get_issue_category_choices, get_issue_citizen_group_1_choices,
    get_issue_citizen_group_2_choices, get_issue_status_choices, get_issue_type_choices
)

COUCHDB_GRM_DATABASE = settings.COUCHDB_GRM_DATABASE
COUCHDB_DATABASE_ADMINISTRATIVE_LEVEL = settings.COUCHDB_DATABASE_ADMINISTRATIVE_LEVEL
MAX_LENGTH = 65000


class NewIssueContactForm(forms.Form):
    contact_medium = forms.ChoiceField(label=_('How does the citizen wish to be contacted?'), widget=RadioSelect,
                                       choices=MEDIUM_CHOICES)
    contact_type = forms.ChoiceField(label='', required=False, choices=CONTACT_CHOICES)
    contact = forms.CharField(label='', required=False)

    def __init__(self, *args, **kwargs):
        initial = kwargs.get('initial')
        doc_id = initial.get('doc_id')
        super().__init__(*args, **kwargs)

        grm_db = get_db(COUCHDB_GRM_DATABASE)

        self.fields['contact'].widget.attrs["placeholder"] = _("Please type the contact information")

        document = grm_db[doc_id]
        if 'contact_medium' in document:
            self.fields['contact_medium'].initial = document['contact_medium']
            if document['contact_medium'] == CHOICE_CONTACT:
                if 'type' in document['contact_information'] and document['contact_information']['type']:
                    self.fields['contact_type'].initial = document['contact_information']['type']
                if 'contact' in document['contact_information'] and document['contact_information']['contact']:
                    self.fields['contact'].initial = document['contact_information']['contact']
            else:
                self.fields['contact'].widget.attrs["class"] = "hidden"


class NewIssuePersonForm(forms.Form):
    citizen = forms.CharField(label=_('Enter name of the citizen'), required=False,
                              help_text=_('This is an optional field'))
    citizen_type = forms.ChoiceField(label=_(''), widget=RadioSelect, required=False,
                                     choices=CITIZEN_TYPE_CHOICES, help_text=_('This is an optional field'))
    citizen_age_group = forms.ChoiceField(label=_('Enter age group'), required=False,
                                          help_text=_('This is an optional field'))
    gender = forms.ChoiceField(label=_('Choose gender'), required=False, help_text=_('This is an optional field'),
                               choices=GENDER_CHOICES)
    citizen_group_1 = forms.ChoiceField(label=_('Religion, Nationality'), required=False,
                                        help_text=_('This is an optional field'))
    citizen_group_2 = forms.ChoiceField(label=_('Religion, Nationality'), required=False,
                                        help_text=_('This is an optional field'))

    def __init__(self, *args, **kwargs):
        initial = kwargs.get('initial')
        doc_id = initial.get('doc_id')
        super().__init__(*args, **kwargs)

        grm_db = get_db(COUCHDB_GRM_DATABASE)

        citizen_age_groups = get_issue_age_group_choices(grm_db)
        self.fields['citizen_age_group'].widget.choices = citizen_age_groups
        self.fields['citizen_age_group'].choices = citizen_age_groups

        citizen_group_1_choices = get_issue_citizen_group_1_choices(grm_db)
        self.fields['citizen_group_1'].widget.choices = citizen_group_1_choices
        self.fields['citizen_group_1'].choices = citizen_group_1_choices

        citizen_group_2_choices = get_issue_citizen_group_2_choices(grm_db)
        self.fields['citizen_group_2'].widget.choices = citizen_group_2_choices
        self.fields['citizen_group_2'].choices = citizen_group_2_choices

        document = grm_db[doc_id]

        if 'citizen' in document:
            self.fields['citizen'].initial = document['citizen']

        if 'citizen_type' in document:
            self.fields['citizen_type'].initial = document['citizen_type']

        if 'citizen_age_group' in document and document['citizen_age_group']:
            self.fields['citizen_age_group'].initial = document['citizen_age_group']['id']

        if 'gender' in document:
            self.fields['gender'].initial = document['gender']

        if 'citizen_group_1' in document and document['citizen_group_1']:
            self.fields['citizen_group_1'].initial = document['citizen_group_1']['id']

        if 'citizen_group_2' in document and document['citizen_group_2']:
            self.fields['citizen_group_2'].initial = document['citizen_group_2']['id']


class NewIssueDetailsForm(forms.Form):
    intake_date = forms.DateTimeField(label=_('Date of intake'), input_formats=['%d/%m/%Y'],
                                      help_text="Date when the issue was recorded on the GRM")
    issue_date = forms.DateTimeField(label=_('Date of issue'), input_formats=['%d/%m/%Y'],
                                     help_text="Date when the issue occurred")
    issue_type = forms.ChoiceField(label=_('What are you reporting'))
    category = forms.ChoiceField(label=_('Choose type of grievance'))
    description = forms.CharField(label=_('Briefly describe the issue'), max_length=2000, widget=forms.Textarea(
        attrs={'rows': '3', 'placeholder': _('Please describe the issue')}))
    ongoing_issue = forms.BooleanField(label=_('Current event or multiple occurrences'),
                                       widget=forms.CheckboxInput, required=False)

    def __init__(self, *args, **kwargs):
        initial = kwargs.get('initial')
        doc_id = initial.get('doc_id')
        super().__init__(*args, **kwargs)

        grm_db = get_db(COUCHDB_GRM_DATABASE)
        types = get_issue_type_choices(grm_db)
        self.fields['issue_type'].widget.choices = types
        self.fields['issue_type'].choices = types
        categories = get_issue_category_choices(grm_db)
        self.fields['category'].widget.choices = categories
        self.fields['category'].choices = categories

        self.fields['intake_date'].widget.attrs['class'] = self.fields['issue_date'].widget.attrs[
            'class'] = 'form-control datetimepicker-input'
        self.fields['intake_date'].widget.attrs['data-target'] = '#intake_date'
        self.fields['issue_date'].widget.attrs['data-target'] = '#issue_date'

        document = grm_db[doc_id]
        if 'description' in document and document['description']:
            self.fields['description'].initial = document['description']
        if 'issue_type' in document and document['issue_type']:
            self.fields['issue_type'].initial = document['issue_type']['id']
        if 'category' in document and document['category']:
            self.fields['category'].initial = document['category']['id']
        if 'ongoing_issue' in document:
            self.fields['ongoing_issue'].initial = document['ongoing_issue']


class NewIssueLocationForm(forms.Form):
    administrative_region = forms.ChoiceField()
    administrative_region_value = forms.CharField(label='', required=False)

    def __init__(self, *args, **kwargs):
        initial = kwargs.get('initial')
        doc_id = initial.get('doc_id')
        super().__init__(*args, **kwargs)

        adl_db = get_db(COUCHDB_DATABASE_ADMINISTRATIVE_LEVEL)
        label = get_administrative_regions_by_level(adl_db)[0]['administrative_level'].title()
        self.fields['administrative_region'].label = label

        administrative_region_choices = get_administrative_region_choices(adl_db)
        self.fields['administrative_region'].widget.choices = administrative_region_choices
        self.fields['administrative_region'].choices = administrative_region_choices
        self.fields['administrative_region'].widget.attrs['class'] = "region"
        self.fields['administrative_region_value'].widget.attrs['class'] = "hidden"

        grm_db = get_db(COUCHDB_GRM_DATABASE)
        document = grm_db[doc_id]
        if 'administrative_region' in document and document['administrative_region']:
            administrative_id = document['administrative_region']['administrative_id']
            self.fields['administrative_region_value'].initial = administrative_id
            self.fields['administrative_region'].initial = get_base_administrative_id(adl_db, administrative_id)


class NewIssueConfirmForm(NewIssueLocationForm, NewIssueDetailsForm, NewIssuePersonForm, NewIssueContactForm):

    def __init__(self, *args, **kwargs):
        NewIssueContactForm.__init__(self, *args, **kwargs)
        NewIssuePersonForm.__init__(self, *args, **kwargs)
        NewIssueDetailsForm.__init__(self, *args, **kwargs)
        NewIssueLocationForm.__init__(self, *args, **kwargs)


class SearchIssueForm(forms.Form):
    start_date = forms.DateTimeField(label=_('Start Date'))
    end_date = forms.DateTimeField(label=_('End Date'))
    code = forms.CharField(label=_('ID Number / Access Code'))
    assigned_to = forms.ChoiceField()
    category = forms.ChoiceField()
    type = forms.ChoiceField()
    status = forms.ChoiceField()
    administrative_region = forms.ChoiceField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        grm_db = get_db(COUCHDB_GRM_DATABASE)

        self.fields['start_date'].widget.attrs['class'] = self.fields['end_date'].widget.attrs[
            'class'] = 'form-control datetimepicker-input'
        self.fields['start_date'].widget.attrs['data-target'] = '#start_date'
        self.fields['end_date'].widget.attrs['data-target'] = '#end_date'
        self.fields['assigned_to'].widget.choices = get_government_worker_choices()
        self.fields['category'].widget.choices = get_issue_category_choices(grm_db)
        self.fields['type'].widget.choices = get_issue_type_choices(grm_db)
        self.fields['status'].widget.choices = get_issue_status_choices(grm_db)

        adl_db = get_db(COUCHDB_DATABASE_ADMINISTRATIVE_LEVEL)
        label = get_administrative_regions_by_level(adl_db)[0]['administrative_level'].title()
        self.fields['administrative_region'].label = label
        self.fields['administrative_region'].widget.choices = get_administrative_region_choices(adl_db)
        self.fields['administrative_region'].widget.attrs['class'] = "region"


class IssueDetailsForm(forms.Form):
    assignee = forms.ChoiceField(label=_('Assigned to'))

    def __init__(self, *args, **kwargs):
        initial = kwargs.get('initial')
        doc_id = initial.get('doc_id')
        super().__init__(*args, **kwargs)

        grm_db = get_db(COUCHDB_GRM_DATABASE)
        self.fields['assignee'].widget.choices = get_government_worker_choices(False)

        document = grm_db[doc_id]
        if type(document['assignee']) == dict:
            self.fields['assignee'].initial = document['assignee']['id']


class IssueCommentForm(forms.Form):
    comment = forms.CharField(label='', max_length=MAX_LENGTH, widget=forms.Textarea(
        attrs={'rows': '3', 'placeholder': _('Add comment')}))


class IssueOpenStatusForm(forms.Form):
    open_reason = forms.CharField(label='', max_length=MAX_LENGTH, widget=forms.Textarea(attrs={'rows': '3'}))

    def __init__(self, *args, **kwargs):
        initial = kwargs.get('initial')
        doc_id = initial.get('doc_id')
        super().__init__(*args, **kwargs)

        grm_db = get_db(COUCHDB_GRM_DATABASE)
        document = grm_db[doc_id]
        self.fields['open_reason'].initial = document['open_reason'] if 'open_reason' in document else ''


class IssueResearchResultForm(forms.Form):
    research_result = forms.CharField(label='', max_length=MAX_LENGTH, widget=forms.Textarea(attrs={'rows': '3'}))

    def __init__(self, *args, **kwargs):
        initial = kwargs.get('initial')
        doc_id = initial.get('doc_id')
        super().__init__(*args, **kwargs)

        grm_db = get_db(COUCHDB_GRM_DATABASE)
        document = grm_db[doc_id]
        self.fields['research_result'].initial = document['research_result'] if 'research_result' in document else ''


class IssueRejectReasonForm(forms.Form):
    reject_reason = forms.CharField(label='', max_length=MAX_LENGTH, widget=forms.Textarea(attrs={'rows': '3'}))

    def __init__(self, *args, **kwargs):
        initial = kwargs.get('initial')
        doc_id = initial.get('doc_id')
        super().__init__(*args, **kwargs)

        grm_db = get_db(COUCHDB_GRM_DATABASE)
        document = grm_db[doc_id]
        self.fields['reject_reason'].initial = document['reject_reason'] if 'reject_reason' in document else ''
