from django import forms
from django.contrib import admin
from django.contrib.auth.hashers import make_password
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from privacy.models import IssueCategoryPassword
from grm.utils import cryptography_fernet_encrypt
from issue.models import IssueCategory


# class IssueCategoryPasswordForm(forms.ModelForm):
#     class Meta:
#         model = IssueCategoryPassword
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


class CustomIssueCategoryPasswordFormChangeForm(forms.ModelForm):
    password = forms.CharField(label='', max_length=7, min_length=7,widget=forms.PasswordInput(attrs={'placeholder': _('Password')}))
    _password = None
    _issue_category_key = None
    class Meta:
        model = IssueCategoryPassword
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

        # Le "key" utilisé comme matériel de clé Fernet (cf. save() ci-dessous) était l'`_id`
        # CouchDB du document `issue_category` — un simple identifiant opaque et stable, jamais
        # réinterprété ailleurs. Son équivalent Postgres est l'UUID `IssueCategory.pk` (résolu ici
        # via `legacy_id`, l'ancien id numérique CouchDB toujours utilisé côté formulaire).
        category = IssueCategory.objects.filter(legacy_id=issue_category_id).first()
        self._issue_category_key = str(category.pk) if category else None

        if not self._issue_category_key:
            raise ValidationError(
                    _("We can't find this category informations."),
                    code="error_category",
                )
        
        return issue_category_id
    
    def save(self, commit=True):
        
        instance = super(CustomIssueCategoryPasswordFormChangeForm, self).save(commit=False)
 
        instance.key = self._issue_category_key
        instance.password_data_encrypt = cryptography_fernet_encrypt(self._password, instance.key)


        if commit:
            self.save_m2m()
            instance.save()

        return instance
    

class CustomIssueCategoryPasswordAdmin(admin.ModelAdmin):
    form = CustomIssueCategoryPasswordFormChangeForm
    # add_form = IssueCategoryPasswordForm
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
    
    raw_id_fields = (
        'user',
    )





admin.site.register(IssueCategoryPassword, CustomIssueCategoryPasswordAdmin)