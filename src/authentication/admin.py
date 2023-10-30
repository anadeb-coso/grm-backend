from django import forms
from django.contrib import admin
from django.contrib.admin.models import LogEntry
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import UserChangeForm
from django.forms.fields import EmailField
from django.contrib import messages
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError

from authentication.models import GovernmentWorker, User, Pdata, Cdata
# from grm.my_librairies.mail.send_mail import send_email
# from authentication.utils import get_validation_code


class UserWithEmptyPasswordCreationForm(forms.ModelForm):
    class Meta:
        model = User
        fields = (
            "email",
        )
        field_classes = {'email': EmailField}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self._meta.model.EMAIL_FIELD in self.fields:
            self.fields[self._meta.model.EMAIL_FIELD].widget.attrs['autofocus'] = True
        self.fields['first_name'].required = True
        self.fields['last_name'].required = True
    
    # def save(self, commit=True):
        
    #     instance = super(UserWithEmptyPasswordCreationForm, self).save(commit=False)
        
    #     try:
    #         msg = send_email(
    #             _("Validation code for your GRM account"),
    #             "mail/send/comment",
    #             {
    #                 "datas": {
    #                     _("Title"): _("Validation code for your GRM account"),
    #                     _("Code"): get_validation_code(instance.email),
    #                     _("Comment"): _("Please do not share this code with anyone until it has been used.")
    #                 },
    #                 "user": {
    #                     _("Name"): f"{instance.first_name} {instance.last_name}",
    #                     _("Phone"): instance.phone_number,
    #                     _("Email"): instance.email
    #                 },
    #                 # "url": f"{request.scheme}://{request.META['HTTP_HOST']}{reverse_lazy('dashboard:facilitators:detail', args=[no_sql_db_name])}"
    #             },
    #             [instance.email]
    #         )
    #     except Exception as exc:
    #         pass

    #     if commit:
    #         self.save_m2m()
    #         instance.save()

    #     return instance



class CustomUserChangeForm(UserChangeForm):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['first_name'].required = True
        self.fields['last_name'].required = True


class UserAdmin(BaseUserAdmin):
    form = CustomUserChangeForm
    add_form = UserWithEmptyPasswordCreationForm
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'first_name', 'last_name', 'photo', 'phone_number'),
        }),
    )
    fieldsets = (
        (None, {
            'fields': ('username', 'password', 'first_name', 'last_name', 'photo', 'email', 'is_active', 'is_staff',
                       'is_superuser', 'groups', 'user_permissions')
        }),
    )
    list_display = ('id', 'email', 'username', 'first_name', 'last_name', 'is_staff')


class GovernmentWorkerForm(forms.ModelForm):
    class Meta:
        model = GovernmentWorker
        fields = '__all__'

    # def save(self, commit=True):
        
    #     instance = super(GovernmentWorkerForm, self).save(commit=False)
        
    #     try:
    #        instance.administrative_ids = list(
    #            set(
    #                (instance.administrative_ids if instance.administrative_ids else list()) + [instance.administrative_id]
    #            )
    #        )
    #     except Exception as exc:
    #         print(exc)

    #     if commit:
    #         self.save_m2m()
    #         instance.save()

    #     return instance

    def clean_administrative_ids(self):
        administrative_ids = self.cleaned_data['administrative_ids']
        if administrative_ids == None or type(administrative_ids) == list:
            try:
                administrative_id = self.cleaned_data['administrative_id']
                if not administrative_ids:
                    administrative_ids = []
                if not administrative_id in administrative_ids:
                    administrative_ids.append(administrative_id)
            except Exception as exc:
                print(exc)
                
            return administrative_ids
        raise ValidationError(
            _("The 'administrative levels' isn't validated"),
            code="wrong_administrative_ids",
        )
    
class GovernmentWorkerAdmin(admin.ModelAdmin):
    form = GovernmentWorkerForm
    fields = (
        'user',
        'department',
        'administrative_id',
        'administrative_ids',
    )
    raw_id_fields = (
        'user',
    )
    list_display = (
        'id',
        'user',
        'department',
        'administrative_id',
    )
    search_fields = (
        'id',
        'user__email',
        'department',
        'administrative_id',
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user')



class LogEntryAdmin(admin.ModelAdmin):
    list_filter = [
        'content_type',
        'action_flag'
    ]

    search_fields = [
        'user__username',
        'object_repr',
        'change_message'
    ]

    list_display = [
        'action_time',
        'user',
        'content_type',
        'action_flag',
        'change_message',
    ]

    def queryset(self, request):
        return super().queryset(request).prefetch_related('content_type')


admin.site.register(User, UserAdmin)
admin.site.register(GovernmentWorker, GovernmentWorkerAdmin)
admin.site.register(Pdata)
admin.site.register(Cdata)
admin.site.register(LogEntry, LogEntryAdmin)
