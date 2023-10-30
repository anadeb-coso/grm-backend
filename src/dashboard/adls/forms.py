from django import forms
from django.utils.translation import gettext_lazy as _

from authentication import ADL, MAJOR
from client import get_db
from dashboard.forms.forms import FileForm
from dashboard.customers_fields import CustomerIntegerRangeField
from authentication.models import User
from administrativelevels.models import AdministrativeLevel
from grm.call_objects_from_other_db import mis_objects_call


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

        document = get_db()[self.doc_id]
        self.fields['name'].initial = document['representative']['name']
        self.fields['phone'].initial = document['representative']['phone']
        self.fields['email'].initial = document['representative']['email']

    def clean_email(self):
        email = self.cleaned_data['email'].lower()
        selector = {
            "$and": [
                {
                    "representative.email": email
                },
                {
                    "type": {
                        "$in": [ADL, MAJOR]
                    }
                }
            ]
        }
        eadl_db = get_db()

        docs = eadl_db.get_query_result(selector)
        doc = docs[0][0] if docs[0] else None
        if doc and doc['_id'] != self.doc_id:
            self.add_error('email', _("This email is already registered."))
        return email


class GovernmentWorkerAdlProfileForm(forms.Form):
    department = CustomerIntegerRangeField(min_value=1, default=1)
    administrative_level = forms.ChoiceField(required=True, label=_('administrative level'))
    administrative_levels = forms.MultipleChoiceField(required=True, label=_('administrative levels'))

    doc_id = ""

    def __init__(self, *args, **kwargs):
        initial = kwargs.get('initial')
        self.doc_id = initial.get('doc_id')
        super().__init__(*args, **kwargs)

        user_doc = get_db()[self.doc_id]
        user_obj = User.objects.get(id=user_doc['representative']['id'])
        
        adls = [(str(obj.id), f'{obj.type}: {obj.name} {f"({obj.parent})" if obj.parent else "(TOGO)"}') for obj in mis_objects_call.get_all_objects(AdministrativeLevel)]

        self.fields['administrative_level'].choices = adls
        self.fields['administrative_levels'].choices = adls
        
        if hasattr(user_obj, 'governmentworker'):
            if user_obj.governmentworker.administrative_id:
                self.fields['administrative_level'].initial = user_obj.governmentworker.administrative_id
            if user_obj.governmentworker.administrative_ids:
                self.fields['administrative_levels'].initial = user_obj.governmentworker.administrative_ids
        
        
