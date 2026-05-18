from django.contrib import admin
from django import forms
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError

from issue.models import Wave
# Register your models here.


class WaveForm(forms.ModelForm):
    class Meta:
        model = Wave
        fields = '__all__'

    def clean_administrative_ids(self):
        administrative_ids = self.cleaned_data['administrative_ids']
        if administrative_ids == None or type(administrative_ids) == list:
            try:
                if not administrative_ids:
                    administrative_ids = []
            except Exception as exc:
                print(exc)
                
            return administrative_ids
        raise ValidationError(
            _("The 'administrative levels' isn't validated"),
            code="wrong_administrative_ids",
        )
    
class WaveAdmin(admin.ModelAdmin):
    form = WaveForm
    fields = (
        'number',
        'description',
        'administrative_ids',
        'begin',
        'end',
    )
    list_display = (
        'id',
        'number',
        'description',
        'begin',
        'end',
    )
    search_fields = (
        'id',
        'number',
        'description',
        'administrative_ids',
        'begin',
        'end',
    )



admin.site.register(Wave, WaveAdmin)