from django.core.validators import RegexValidator
from django.utils.translation import ugettext as _

_password_regex = r'^(?=.*[A-Za-z])(?=.*\d)[A-Za-z\d]{8,}$'
password_regex = RegexValidator(
    _password_regex, 
    _("At least eight characters, including at least one letter and one number")
)