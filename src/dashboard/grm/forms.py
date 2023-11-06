from django import forms
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from django.template.defaultfilters import filesizeformat

from authentication.models import get_government_worker_choices
from client import get_db
from dashboard.forms.widgets import RadioSelect
from dashboard.grm import (
    CHOICE_CONTACT, CITIZEN_TYPE_CHOICES, CONTACT_CHOICES, GENDER_CHOICES, MEDIUM_CHOICES,
    CITIZEN_OR_GROUP_CHOICES
)
from grm.utils import (
    get_administrative_region_choices, get_base_administrative_id, get_administrative_regions_by_level,
    get_issue_age_group_choices, get_issue_category_choices, get_issue_citizen_group_1_choices,
    get_issue_citizen_group_2_choices, get_issue_status_choices, get_issue_type_choices
)

COUCHDB_GRM_DATABASE = settings.COUCHDB_GRM_DATABASE
COUCHDB_DATABASE_ADMINISTRATIVE_LEVEL = settings.COUCHDB_DATABASE_ADMINISTRATIVE_LEVEL
MAX_LENGTH = 65000



class CheckPasswordForm(forms.Form):
    password = forms.CharField(max_length=7, min_length=7, widget=forms.PasswordInput(), label=_("Password"))


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
    citizen = forms.CharField(label=_('Enter name of the citizen or of the group'), required=False,
                              help_text=_('This is an optional field'))
    citizen_type = forms.ChoiceField(label=_(''), widget=RadioSelect, required=False,
                                     choices=CITIZEN_TYPE_CHOICES, help_text=_('This is an optional field'))
    citizen_or_group = forms.ChoiceField(label=_('Complainant type'), widget=RadioSelect, required=False,
                                     choices=CITIZEN_OR_GROUP_CHOICES, help_text=_('This is an optional field'))
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
        
        if 'citizen_or_group' in document:
            self.fields['citizen_or_group'].initial = document['citizen_or_group']

        if 'citizen_age_group' in document and document['citizen_age_group']:
            self.fields['citizen_age_group'].initial = document['citizen_age_group']['id']

        if 'gender' in document:
            self.fields['gender'].initial = document['gender']

        if 'citizen_group_1' in document and document['citizen_group_1']:
            self.fields['citizen_group_1'].initial = document['citizen_group_1']['id']

        if 'citizen_group_2' in document and document['citizen_group_2']:
            self.fields['citizen_group_2'].initial = document['citizen_group_2']['id']
        
        if len(citizen_group_1_choices) <= 1:
            del self.fields['citizen_group_1']
        if len(citizen_group_2_choices) <= 1:
            del self.fields['citizen_group_2']



class NewIssueDetailsForm(forms.Form):
    intake_date = forms.DateTimeField(label=_('Date of intake'), input_formats=['%d/%m/%Y'],
                                      help_text="Date when the issue was recorded on the GRM")
    issue_date = forms.DateTimeField(label=_('Date of issue'), input_formats=['%d/%m/%Y'],
                                     help_text="Date when the issue occurred")
    # issue_type = forms.ChoiceField(label=_('What are you reporting'))
    category = forms.ChoiceField(label=_('Choose type of grievance'))
    description = forms.CharField(label=_('Briefly describe the issue'), max_length=2000, widget=forms.Textarea(
        attrs={'rows': '3', 'placeholder': _('Please describe the issue')}))
    issue_password = forms.CharField(label=_('Password'), max_length=7, min_length=7, required=False,
                                     widget=forms.PasswordInput(attrs={'placeholder': _('Password')}))

    ongoing_issue = forms.BooleanField(label=_('On going event'),
                                       widget=forms.CheckboxInput, required=False)
    event_recurrence = forms.BooleanField(label=_('Event has occurred several times'),
                                       widget=forms.CheckboxInput, required=False)

    def __init__(self, *args, **kwargs):
        initial = kwargs.get('initial')
        doc_id = initial.get('doc_id')
        user = initial.get('user')
        super().__init__(*args, **kwargs)
        
        grm_db = get_db(COUCHDB_GRM_DATABASE)
        # types = get_issue_type_choices(grm_db)
        # self.fields['issue_type'].widget.choices = types
        # self.fields['issue_type'].choices = types
        categories = get_issue_category_choices(grm_db)
        categories = [cat for cat in categories if (str(cat[0]) not in ('4', '7')) or (str(cat[0]) in ('4', '7') and user.groups.filter(name="Privacy").exists())]
        self.fields['category'].widget.choices = categories
        self.fields['category'].choices = categories

        self.fields['intake_date'].widget.attrs['class'] = self.fields['issue_date'].widget.attrs[
            'class'] = 'form-control datetimepicker-input'
        self.fields['intake_date'].widget.attrs['data-target'] = '#intake_date'
        self.fields['issue_date'].widget.attrs['data-target'] = '#issue_date'
        self.fields['issue_password'].help_text = '<span style="color:black;">'+_("Password used to view original description")+'</span>'

        document = grm_db[doc_id]
        if 'description' in document and document['description']:
            self.fields['description'].initial = document['description']
        # if 'issue_type' in document and document['issue_type']:
        #     self.fields['issue_type'].initial = document['issue_type']['id']
        if 'category' in document and document['category']:
            self.fields['category'].initial = document['category']['id']
        if 'ongoing_issue' in document:
            self.fields['ongoing_issue'].initial = document['ongoing_issue']
        if 'event_recurrence' in document:
            self.fields['event_recurrence'].initial = document['event_recurrence']


class NewIssueLocationForm(forms.Form):
    administrative_region = forms.ChoiceField()
    administrative_region_value = forms.CharField(label='', required=False)
    location_description = forms.CharField(label=_("Location description"), required=False,
        help_text=_("Please enter additional details about the location\nthat might help resolve the issue (e.g. street\naddress, street corner, or description of location)."), 
        max_length=2000, widget=forms.Textarea(
        attrs={'rows': '3', 'placeholder': _('Please provide any additional details.')}))
    structure_in_charge = forms.CharField(
        # label=_('Structure in charge of this complaint'), 
        label=_('Committee/Structure in charge'), 
        required=False,
        help_text=_('This is an optional field'))
    structure_in_charge_phone = forms.CharField(label=_('Structure telephone number'), required=False,
                              help_text=_('This is an optional field'))
    structure_in_charge_email = forms.EmailField(label=_('Structure e-mail address'), required=False,
                              help_text=_('This is an optional field'))

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

        if 'location_info' in document and 'location_description' in document['location_info'] and document['location_info']['location_description']:
            self.fields['location_description'].initial = document['location_info']['location_description']
            
        if 'structure_in_charge' in document:
            if 'name' in document['structure_in_charge'] and  document['structure_in_charge']['name']:
                self.fields['structure_in_charge'].initial = document['structure_in_charge']['name']
            if 'phone' in document['structure_in_charge'] and  document['structure_in_charge']['phone']:
                self.fields['structure_in_charge_phone'].initial = document['structure_in_charge']['phone']
            if 'email' in document['structure_in_charge'] and  document['structure_in_charge']['email']:
                self.fields['structure_in_charge_email'].initial = document['structure_in_charge']['email']



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
    # type = forms.ChoiceField()
    status = forms.ChoiceField()
    administrative_region = forms.ChoiceField()
    other = forms.ChoiceField()
    reported_by = forms.ChoiceField()
    publish = forms.ChoiceField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        grm_db = get_db(COUCHDB_GRM_DATABASE)

        self.fields['start_date'].widget.attrs['class'] = self.fields['end_date'].widget.attrs[
            'class'] = 'form-control datetimepicker-input'
        self.fields['start_date'].widget.attrs['data-target'] = '#start_date'
        self.fields['end_date'].widget.attrs['data-target'] = '#end_date'
        self.fields['assigned_to'].widget.choices = get_government_worker_choices()
        self.fields['category'].widget.choices = get_issue_category_choices(grm_db)
        # self.fields['type'].widget.choices = get_issue_type_choices(grm_db)
        self.fields['status'].widget.choices = get_issue_status_choices(grm_db)
        self.fields['other'].widget.choices = [('', ''), ('Escalate', _('Escalated'))]
        self.fields['reported_by'].widget.choices = get_government_worker_choices()
        self.fields['publish'].widget.choices = [('', ''), (True, _('Publish')), (False, _('Unpublish'))]

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
        self.fields['assignee'].widget.choices = get_government_worker_choices(True)

        document = grm_db[doc_id]
        if type(document['assignee']) == dict:
            self.fields['assignee'].initial = document['assignee']['id']


class IssueCommentForm(forms.Form):
    comment = forms.CharField(label='', max_length=MAX_LENGTH, widget=forms.Textarea(
        attrs={'rows': '3', 'placeholder': _('Add comment')}))
    issue_password_comment = forms.CharField(label='', max_length=7, min_length=7, required=False,
                                             widget=forms.PasswordInput(attrs={'placeholder': _('Password')}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['issue_password_comment'].help_text = '<span style="color:black;">'+_("Password used to view the add.")+'</span>'


class IssueReasonCommentForm(forms.Form):
    reason = forms.CharField(label='', max_length=MAX_LENGTH, widget=forms.Textarea(
        attrs={'rows': '3', 'placeholder': _('Add decision')}))
    issue_password_reason = forms.CharField(label='', max_length=7, min_length=7, required=False,
                                            widget=forms.PasswordInput(attrs={'placeholder': _('Password')}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['issue_password_reason'].help_text = '<span style="color:black;">'+_("Password used to view the add.")+'</span>'


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
    file_pdf = forms.FileField(label=_('Attach PV of reconciliation'), help_text=_('Allowed file size less than or equal to 2 MB'), required=True)
    issue_password = forms.CharField(label='', max_length=7, min_length=7, required=False,
                                            widget=forms.PasswordInput(attrs={'placeholder': _('Password')}))
    
    default_error_messages = {
        'file_size': _('Select a file size less than or equal to %(max_size)s. The selected file size is %(size)s.')}
    

    def __init__(self, *args, **kwargs):
        initial = kwargs.get('initial')
        doc_id = initial.get('doc_id')
        super().__init__(*args, **kwargs)
        self.fields['issue_password'].help_text = '<span style="color:black;">'+_("Password used to view the add.")+'</span>'

        grm_db = get_db(COUCHDB_GRM_DATABASE)
        document = grm_db[doc_id]
        self.fields['research_result'].initial = document['research_result'] if 'research_result' in document else ''
    
    def clean_file_pdf(self):
        max_upload_size = settings.MAX_UPLOAD_SIZE
        value = self.cleaned_data.get('file_pdf')
        if value and value.size > max_upload_size:
            raise forms.ValidationError(
                self.default_error_messages['file_size'] % {
                    'max_size': filesizeformat(max_upload_size),
                    'size': filesizeformat(value.size)})
        return value
    
class IssueSetUnresolvedForm(forms.Form):
    unresolved_reason = forms.CharField(label='', max_length=MAX_LENGTH, widget=forms.Textarea(attrs={'rows': '3'}))

    def __init__(self, *args, **kwargs):
        initial = kwargs.get('initial')
        doc_id = initial.get('doc_id')
        super().__init__(*args, **kwargs)

        grm_db = get_db(COUCHDB_GRM_DATABASE)
        document = grm_db[doc_id]
        self.fields['unresolved_reason'].initial = document['unresolved_reason'] if 'unresolved_reason' in document else ''

class IssueIssueEscalateForm(forms.Form):
    escalate_reason = forms.CharField(label='', max_length=MAX_LENGTH, widget=forms.Textarea(attrs={'rows': '3'}))
    file_pdf = forms.FileField(label=_('Attach the complaint transfer file to the top level'), 
                               help_text=_('Allowed file size less than or equal to 2 MB'), required=False)
    issue_password = forms.CharField(label='', max_length=7, min_length=7, required=False,
                                            widget=forms.PasswordInput(attrs={'placeholder': _('Password')}))
    
    default_error_messages = {
        'file_size': _('Select a file size less than or equal to %(max_size)s. The selected file size is %(size)s.')}
    

    def __init__(self, *args, **kwargs):
        initial = kwargs.get('initial')
        doc_id = initial.get('doc_id')
        super().__init__(*args, **kwargs)
        self.fields['issue_password'].help_text = '<span style="color:black;">'+_("Password used to view the add.")+'</span>'


        grm_db = get_db(COUCHDB_GRM_DATABASE)
        document = grm_db[doc_id]
        self.fields['escalate_reason'].initial = document['escalate_reason'] if 'escalate_reason' in document else ''
    
    def clean_file_pdf(self):
        max_upload_size = settings.MAX_UPLOAD_SIZE
        value = self.cleaned_data.get('file_pdf')
        if value and value.size > max_upload_size:
            raise forms.ValidationError(
                self.default_error_messages['file_size'] % {
                    'max_size': filesizeformat(max_upload_size),
                    'size': filesizeformat(value.size)})
        return value

class IssueIssuePublishForm(forms.Form):
    issue_description = forms.CharField(label='', max_length=MAX_LENGTH, widget=forms.Textarea(attrs={'rows': '3'}))
    issue_password = forms.CharField(label='', max_length=7, min_length=7,widget=forms.PasswordInput(attrs={'placeholder': _('Password')}))

    def __init__(self, *args, **kwargs):
        initial = kwargs.get('initial')
        doc_id = initial.get('doc_id')
        super().__init__(*args, **kwargs)

        grm_db = get_db(COUCHDB_GRM_DATABASE)
        document = grm_db[doc_id]
        self.fields['issue_description'].initial = document['description'] if 'description' in document else ''
        self.fields['issue_password'].help_text = '<span style="color:black;">'+_("Password used to view original description")+'</span>'

class IssueIssueUnpublishForm(forms.Form):
    
    def __init__(self, *args, **kwargs):
        initial = kwargs.get('initial')
        doc_id = initial.get('doc_id')
        super().__init__(*args, **kwargs)



class IssueRejectReasonForm(forms.Form):
    reject_reason = forms.CharField(label='', max_length=MAX_LENGTH, widget=forms.Textarea(attrs={'rows': '3'}))

    def __init__(self, *args, **kwargs):
        initial = kwargs.get('initial')
        doc_id = initial.get('doc_id')
        super().__init__(*args, **kwargs)

        grm_db = get_db(COUCHDB_GRM_DATABASE)
        document = grm_db[doc_id]
        self.fields['reject_reason'].initial = document['reject_reason'] if 'reject_reason' in document else ''


class IssueCategoryForm(forms.Form):
    category = forms.ChoiceField(label=_('Category'))

    def __init__(self, *args, **kwargs):
        initial = kwargs.get('initial')
        doc_id = initial.get('doc_id')
        user = initial.get('user')
        super().__init__(*args, **kwargs)

        grm_db = get_db(COUCHDB_GRM_DATABASE)
        categories = get_issue_category_choices(grm_db)
        categories = [cat for cat in categories if (str(cat[0]) not in ('4', '7')) or (str(cat[0]) in ('4', '7') and user.groups.filter(name="Privacy").exists())]
        self.fields['category'].widget.choices = categories
        self.fields['category'].choices = categories
        
        document = grm_db[doc_id]
        
        if 'category' in document and document['category']:
            self.fields['category'].initial = document['category']['id']
