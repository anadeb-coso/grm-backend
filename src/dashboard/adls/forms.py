from django import forms
from django.utils.translation import gettext_lazy as _

from dashboard.forms.forms import FileForm
from dashboard.customers_fields import CustomerIntegerRangeField
from authentication.models import User
from administrativelevels.models import AdministrativeLevel
from grm.call_objects_from_other_db import mis_objects_call
from issue.models import Adl


class PasswordConfirmForm(forms.Form):
    password = forms.CharField(widget=forms.PasswordInput(), label=_("Password"))


class AdlProfileForm(FileForm):
    name = forms.CharField(max_length=250, label=_("Name"))
    phone = forms.CharField(required=False, max_length=50, label=_('Tel'))
    email = forms.EmailField()
    doc_id = ""

    def __init__(self, *args, **kwargs):
        initial = kwargs.get('initial')
        self.doc_id = initial.get('doc_id')
        super().__init__(*args, **kwargs)
        self.fields['file'].required = False
        self.fields['file'].widget.attrs["class"] = "hidden"

        adl = Adl.objects.select_related('representative').get(pk=self.doc_id)
        representative = adl.representative
        self.fields['name'].initial = representative.name if representative else ''
        self.fields['phone'].initial = representative.phone_number if representative else ''
        self.fields['email'].initial = representative.email if representative else ''

    def clean_email(self):
        email = self.cleaned_data['email'].lower()
        existing = User.objects.filter(email=email).exclude(
            adl_representations__pk=self.doc_id,
        ).first()
        if existing:
            self.add_error('email', _("This email is already registered."))
        return email


class GovernmentWorkerAdlProfileForm(forms.Form):
    department = CustomerIntegerRangeField(min_value=1, default=1)
    administrative_level = forms.ChoiceField(required=True, label=_('administrative level'))
    administrative_levels = forms.MultipleChoiceField(required=False, label=_('Area of ​​intervention'))
    additional_administrative_ids = forms.MultipleChoiceField(required=False, label=_('Additional locations'))

    doc_id = ""

    def __init__(self, *args, **kwargs):
        initial = kwargs.get('initial')
        self.doc_id = initial.get('doc_id')
        super().__init__(*args, **kwargs)

        adl = Adl.objects.select_related('representative').get(pk=self.doc_id)
        user_obj = adl.representative

        adls = [(str(obj.id), f'{obj.type}: {obj.name} {f"({obj.parent})" if obj.parent else "(TOGO)"}') for obj in mis_objects_call.get_all_objects(AdministrativeLevel)]

        self.fields['administrative_level'].choices = [('', '')] + adls
        self.fields['administrative_levels'].choices = adls
        self.fields['additional_administrative_ids'].choices = adls

        if user_obj and hasattr(user_obj, 'governmentworker'):
            if user_obj.governmentworker.administrative_id:
                self.fields['administrative_level'].initial = user_obj.governmentworker.administrative_id
            if user_obj.governmentworker.administrative_ids:
                self.fields['administrative_levels'].initial = user_obj.governmentworker.administrative_ids
            if user_obj.governmentworker.additional_administrative_ids:
                self.fields['additional_administrative_ids'].initial = user_obj.governmentworker.additional_administrative_ids


class CreateAdlProfileForm(forms.Form):
    first_name = forms.CharField(max_length=250, label=_("First name"))
    last_name = forms.CharField(max_length=250, label=_("Last name"))
    phone = forms.CharField(required=False, max_length=50, label=_('Tel'), help_text="Ex:. 22890709080")
    email = forms.EmailField()
    department = CustomerIntegerRangeField(min_value=1, default=1)
    administrative_level = forms.ChoiceField(required=True, label=_('administrative level'))
    administrative_levels = forms.MultipleChoiceField(required=False, label=_('Area of ​​intervention'))
    additional_administrative_ids = forms.MultipleChoiceField(required=False, label=_('Additional locations'))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        adls = [(str(obj.id), f'{obj.type}: {obj.name} {f"({obj.parent})" if obj.parent else "(TOGO)"}') for obj in mis_objects_call.get_all_objects(AdministrativeLevel)]

        self.fields['administrative_level'].choices = [('', '')] + [('1', 'TOGO')] + adls
        self.fields['administrative_levels'].choices = adls
        self.fields['additional_administrative_ids'].choices = adls
