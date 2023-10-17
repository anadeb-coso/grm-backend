from django import forms
from django.contrib import admin
from django.contrib.auth.hashers import make_password
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.conf import settings

from privacy.models import IssueCategpryPassword
from grm.utils import cryptography_fernet_encrypt
from client import get_db

COUCHDB_GRM_DATABASE = settings.COUCHDB_GRM_DATABASE


# class IssueCategpryPasswordForm(forms.ModelForm):
#     class Meta:
#         model = IssueCategpryPassword
#         fields = (
#             "issue_category_id", "password", "user"
#         )

#     def __init__(self, *args, **kwargs):
#         super().__init__(*args, **kwargs)
    
#     def clean_password(self):
#         password = self.cleaned_data['password'].lower()
#         if not (password and len(str(password)) >= 8):
#             raise ValidationError(
#                     _("The password must have 8 characters minimum."),
#                     code="error_password",
#                 )
#         print(make_password(password))
#         return make_password(password)


class CustomIssueCategpryPasswordFormChangeForm(forms.ModelForm):
    password = forms.CharField(label='', max_length=7, min_length=7,widget=forms.PasswordInput(attrs={'placeholder': _('Password')}))
    _password = None
    _issue_category_key = None
    class Meta:
        model = IssueCategpryPassword
        fields = (
            "issue_category_id", "password", "user"
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def clean_password(self):
        password = self.cleaned_data['password']
        self._password = password
        # if not (password and len(str(password)) >= 8):
        #     raise ValidationError(
        #             _("The password must have 8 characters minimum."),
        #             code="error_password",
        #         )
        
        if self.instance.pk:
            # if "pbkdf2_" not in password:
            #     return make_password(password)
            # else:
            #     return password
            raise ValidationError(
                    _("You can't edit the password information."),
                    code="error_password",
                )
        
        return make_password(password)
    
    def clean_issue_category_id(self):
        issue_category_id = self.cleaned_data['issue_category_id']
        
        try:
            self._issue_category_key = get_db(COUCHDB_GRM_DATABASE).get_query_result({
                "id": issue_category_id,
                "type": 'issue_category'
            })[0][0]['_id']
        except Exception:
            self._issue_category_key = None

        if not self._issue_category_key:
            raise ValidationError(
                    _("We can't find this category informations."),
                    code="error_category",
                )
        
        return issue_category_id
    
    def save(self, commit=True):
        
        instance = super(CustomIssueCategpryPasswordFormChangeForm, self).save(commit=False)
 
        instance.key = self._issue_category_key
        instance.password_data_encrypt = cryptography_fernet_encrypt(self._password, instance.key)


        if commit:
            self.save_m2m()
            instance.save()

        return instance
    

class CustomIssueCategpryPasswordAdmin(admin.ModelAdmin):
    form = CustomIssueCategpryPasswordFormChangeForm
    # add_form = IssueCategpryPasswordForm
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ("issue_category_id", "password", "user"),
        }),
    )
    fieldsets = (
        (None, {
            'fields': ("issue_category_id", "password", "user")
        }),
    )
    list_display = ("issue_category_id", "user")

    search_fields = ('id', "issue_category_id", "user__email")





admin.site.register(IssueCategpryPassword, CustomIssueCategpryPasswordAdmin)