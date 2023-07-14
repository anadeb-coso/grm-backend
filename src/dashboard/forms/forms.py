from django import forms
from django.conf import settings
from django.template.defaultfilters import filesizeformat
from django.utils.translation import gettext_lazy as _


class FileForm(forms.Form):
    file = forms.FileField(label='', help_text=_('Allowed file size less than or equal to 2 MB'))
    issue_password_file = forms.CharField(label='', max_length=7, min_length=7, required=False,
                                             widget=forms.PasswordInput(attrs={'placeholder': _('Password')}))

    default_error_messages = {
        'file_size': _('Select a file size less than or equal to %(max_size)s. The selected file size is %(size)s.')}
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['issue_password_file'].help_text = '<span style="color:black;">'+_("Password used to view the add.")+'</span>'

    def clean_file(self):
        max_upload_size = settings.MAX_UPLOAD_SIZE
        value = self.cleaned_data.get('file')
        if value and value.size > max_upload_size:
            raise forms.ValidationError(
                self.default_error_messages['file_size'] % {
                    'max_size': filesizeformat(max_upload_size),
                    'size': filesizeformat(value.size)})
        return value
