from django.contrib.auth import authenticate
from django.contrib.auth.forms import AuthenticationForm
from django.utils.translation import ugettext as _
from django import forms
from django.core.exceptions import ValidationError
import django.contrib.auth.password_validation as validators
from django.contrib.auth.hashers import make_password
import re

from authentication.models import User
from authentication.utils import get_validation_code
from grm.form_utils import password_regex, _password_regex


class EmailAuthenticationForm(AuthenticationForm):
    def __init__(self, request=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].label = _('Email')

    def clean(self):
        email = self.cleaned_data.get('username')
        password = self.cleaned_data.get('password')

        user = User.objects.filter(email__iexact=email).first()

        if not user:
            raise self.get_invalid_login_error()
        if email and password:
            self.user_cache = authenticate(self.request, username=user.username, password=password)
            if self.user_cache is None:
                raise self.get_invalid_login_error()
            else:
                self.confirm_login_allowed(self.user_cache)

        return self.cleaned_data

class RegisterADLForm(forms.Form):
    email = forms.EmailField(widget=forms.TextInput(attrs={"autofocus": True}), label=_('Email'))
    password = forms.CharField(
        label=_("Password"),
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
        # validators=[password_regex]
    )

    error_messages = {
        "email_not_exists": _(
            "Please enter the correct %(email)s sent to you by your supervisor"
        ),
        "inactive": _("This account is inactive."),
        "password_invalide": _("Password invalidate"),
        'duplicated_email': _('A user with that email is already registered.'),
        'credentials': _('Unable to register with provided credentials.'),
        'password_invalide_constraint': _("At least eight characters, including at least one letter and one number"),
        'no_administrative_level_affected': _('No administrative level affected. Contact your superior.')
    }

    def clean(self):
        email = self.cleaned_data.get("email")
        password = self.cleaned_data.get("password")
        user = User.objects.get(email=email) if User.objects.filter(email=email).exists() else None

        # Remplace l'ancienne requête Mango CouchDB (docs `type: adl|major`, `representative.
        # is_active`) : `User.is_active` est directement la même donnée (c'est ce que
        # `dashboard/adls/views.py::ToggleAdlStatusView` bascule), inutile de repasser par un
        # document `Adl` intermédiaire. La restriction aux seuls types `adl`/`major` est retirée
        # (simplification documentée, migration dashboard web) : tout compte Postgres actif sans
        # mot de passe déjà défini peut s'enregistrer via ce flux — la propriété de sécurité qui
        # compte (pas de réinitialisation de mot de passe déguisée en inscription) est préservée
        # ci-dessous.
        if not user or not user.is_active:
            raise ValidationError(
                    self.error_messages.get('credentials'),
                    code="credentials",
                )
        # prevents the sign up is used to reset password
        if user.password:
            raise ValidationError(
                    self.error_messages.get('duplicated_email'),
                    code="duplicated_email",
                )

        try:
            validators.validate_password(password=password)
        except ValidationError as e:
            raise ValidationError(
                self.error_messages["password_invalide"],
                code="password_invalide",
            )
        if not re.match(_password_regex, password):
            raise ValidationError(
                self.error_messages["password_invalide_constraint"],
                code="password_invalide_constraint",
            )

        if user is not None:
            if not user.is_active:
                raise ValidationError(
                    self.error_messages["inactive"],
                    code="inactive",
                )
            elif not user.administrative_level:
                raise ValidationError(self.error_messages["no_administrative_level_affected"],
                    code="no_administrative_level_affected")
        else:
            raise ValidationError(
                self.error_messages["email_not_exists"],
                code="email_not_exists",
            )

        return self.cleaned_data
    

class ConfirmCodeForm(forms.Form):
    code = forms.IntegerField(label=_("Code"), widget=forms.NumberInput(attrs={"min": 0, "minlength": 6}))
    default_error_messages = {
        'invalid': _('Invalid data. Expected a dictionary, but got {datatype}.'),
        'credentials': _('Unable to register with provided credentials.'),
        'duplicated_email': _('A user with that email is already registered.'),
        'wrong_validation_code': _('Unable to register with provided validation code.'),
        "password_invalide": _("Password invalidate"),
        'password_invalide_constraint': _("At least eight characters, including at least one letter and one number")
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        initial = kwargs.get('initial')
        self.email = initial.get('email')
        self.password = initial.get('password')


    def clean(self):

        # cf. RegisterADLForm.clean : même simplification (accès direct à `User`, sans document
        # `Adl` intermédiaire ni restriction de type `adl`/`major`).
        user = User.objects.filter(email__iexact=self.email, is_active=True).first()
        if not user:
            raise ValidationError(
                    self.default_error_messages.get('credentials'),
                    code="credentials",
                )

        # prevents the sign up is used to reset password
        if user.password:
            raise ValidationError(
                    self.default_error_messages.get('duplicated_email'),
                    code="duplicated_email",
                )

        errors = dict()
        try:
            # validate the password and catch the exception
            validators.validate_password(password=self.password)

        # the exception raised here is different than serializers.ValidationError
        except ValidationError as e:
            errors['password'] = list(e.messages)
        if not re.match(_password_regex, self.password):
            errors['password'] = list(self.default_error_messages["password_invalide_constraint"])

        if errors:
            raise ValidationError(
                        self.default_error_messages.get("password_invalide"),
                        code="password_invalide",
                    )

        validation_code = str(self.cleaned_data.get("code"))

        if validation_code != get_validation_code(user.email):
            raise ValidationError(
                        self.default_error_messages.get('wrong_validation_code'),
                        code="wrong_validation_code",
                    )

        # Écriture unique Postgres (l'ancien code écrivait aussi sur le document CouchDB `adl`,
        # désormais retiré — cf. RegisterADLForm.clean).
        user.password = make_password(self.password)
        user.save(update_fields=['password'])

        return self.cleaned_data