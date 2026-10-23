import django.contrib.auth.password_validation as validators
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers, status
from rest_framework.exceptions import APIException
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from authentication.password_change import password_change_required
from authentication.utils import get_validation_code
from authentication.models import User
from issue.models import Adl


class PasswordChangeRequired(APIException):
    """Mot de passe initial (compte créé dans le DCC) pas encore changé : ni jeton ni profil avant le changement
    (écran dédié des applications mobiles, qui appelle le DCC). `code` permet au mobile de reconnaître le cas."""
    status_code = status.HTTP_403_FORBIDDEN
    default_code = 'password_change_required'

    def __init__(self):
        super().__init__({
            'detail': _('You must change your password before your first login.'),
            'code': self.default_code,
        })


class EmailTokenObtainPairSerializer(TokenObtainPairSerializer):
    """`/api/auth/token/` : le mobile envoie l'e-mail saisi dans le champ `username` (écran de
    connexion, et connexion automatique juste après l'inscription). Or `User.save` attribue un
    `username` aléatoire aux comptes créés sans en préciser un (dashboard, import de fichier) :
    SimpleJWT, qui authentifie par `username`, refusait alors ces comptes (« Aucun compte actif »)
    alors que la connexion web, elle, résout l'e-mail (dashboard/authentication/forms.py::
    EmailAuthenticationForm). Même résolution ici ; un vrai `username` reste accepté."""

    def validate(self, attrs):
        login = attrs.get(self.username_field)
        if login:
            user = (
                User.objects.filter(email=login).only('username').first()
                or User.objects.filter(email__iexact=login).only('username').first()
            )
            if user is not None:
                attrs[self.username_field] = user.username
        data = super().validate(attrs)
        if password_change_required(self.user.email):
            raise PasswordChangeRequired()
        return data


def _government_worker_administrative_id(user):
    """Repli pour `administrative_region` quand l'Adl n'a aucune localité : seul
    `GovernmentWorker.administrative_id` est renseigné (cas des comptes nationaux "1" dont
    `administrative_ids` est vide, recopié tel quel dans l'Adl par
    authentication.utils.set_user_government_worker_adl). Sans ce repli, le mobile ne reconnaît
    pas le compte national (IssueSearch/WorkInProgress/Statistic testent
    `administrative_region == '1'`) et ne lui montre que les plaintes qu'il a enregistrées ou qui
    lui sont assignées, alors que la synchronisation lui envoie déjà toutes les plaintes
    (sync.views._issue_full_access lit aussi `administrative_id`)."""
    government_worker = getattr(user, 'governmentworker', None)
    administrative_id = getattr(government_worker, 'administrative_id', None)
    return str(administrative_id) if administrative_id else None


def _facilitator_to_legacy_dict(user):
    """Reproduit la forme historique du document CouchDB `eadls` (`type: adl`/`major`) attendue
    par les anciens endpoints REST pré-WatermelonDB encore routés (register/obtain-auth-credentials,
    consommés par les installations mobiles pas encore mises à jour). Même principe que
    dashboard/adls/serializers.py::adl_to_legacy_dict, dupliqué ici pour éviter une dépendance de
    l'app authentication (racine, utilisée par le mobile) vers l'app dashboard (admin web)."""
    adl = Adl.objects.filter(representative=user).first()
    if adl:
        return {
            '_id': str(adl.pk),
            'type': 'adl',
            'name': adl.name,
            'location_name': adl.location_name,
            'administrative_region': (
                str(adl.administrative_region_ids[0]) if adl.administrative_region_ids
                else _government_worker_administrative_id(user)
            ),
            'administrative_regions': [str(i) for i in adl.administrative_region_ids],
            'smallest_administrative_level_ids': [str(i) for i in adl.smallest_administrative_level_ids],
            'additional_administrative_regions': [str(i) for i in adl.additional_administrative_region_ids],
            'additional_smallest_administrative_level_ids': [str(i) for i in adl.additional_smallest_administrative_level_ids],
            'representative': {
                'id': user.id, 'name': user.name, 'email': user.email,
                'phone': user.phone_number, 'photo': user.photo_url,
                'is_active': user.is_active, #'password': user.password,
                'groups': list(user.groups.values_list('name', flat=True)),
            },
        }
    # Utilisateur sans Adl rattaché (ex ancien document CouchDB `type: major`, jamais repris par
    # migrate_eadls.py qui ne migre que les documents `type: adl`) : dict minimal, pour ne pas
    # faire échouer un vieux client qui attend tout de même une forme `eadl` en réponse.
    return {
        '_id': str(user.id),
        'type': 'major',
        'name': user.name,
        'representative': {
            'id': user.id, 'name': user.name, 'email': user.email,
            'phone': user.phone_number, 'photo': user.photo_url,
            'is_active': user.is_active, 'password': user.password,
        },
    }


class CredentialSerializer(serializers.Serializer):
    doc_id = serializers.CharField()
    eadl = serializers.JSONField()


class UserAuthSerializer(serializers.Serializer):
    email = serializers.CharField(label=_("Email"))
    password = serializers.CharField(
        label=_("Password"),
        style={'input_type': 'password'},
        trim_whitespace=False,
        min_length=8,
        max_length=16,
    )
    default_error_messages = {
        'invalid': _('Invalid data. Expected a dictionary, but got {datatype}.'),
        'credentials': _('Unable to log in with provided credentials.'),
    }

    def validate(self, attrs):
        email = attrs.get('email')
        password = attrs.get('password')

        user = User.objects.filter(email=email, is_active=True).first()
        if not user:
            raise serializers.ValidationError(self.default_error_messages.get('credentials'))

        if email and password:
            if not check_password(password, user.password):
                msg = self.default_error_messages['credentials']
                raise serializers.ValidationError(msg, code='authorization')
        else:
            msg = _('Must include "email" and "password".')
            raise serializers.ValidationError(msg, code='authorization')

        if password_change_required(user.email):
            raise PasswordChangeRequired()

        attrs['doc_id'] = str(user.id)
        attrs['eadl'] = _facilitator_to_legacy_dict(user)
        return attrs


class RegisterSerializer(serializers.Serializer):
    email = serializers.CharField()
    password = serializers.CharField(max_length=16, trim_whitespace=False)
    validation_code = serializers.CharField()
    default_error_messages = {
        'invalid': _('Invalid data. Expected a dictionary, but got {datatype}.'),
        'credentials': _('Unable to register with provided credentials.'),
        'duplicated_email': _('A user with that email is already registered.'),
        'wrong_validation_code': _('Unable to register with provided validation code.'),
        'not_found_email': _('A user with that email has not been found registered.'),
        'no_administrative_level_affected': _('No administrative level affected. Contact your superior.')

    }

    def validate(self, attrs):
        email = attrs.get('email', '').lower()
        password = attrs.get('password')
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            raise serializers.ValidationError(self.default_error_messages.get('not_found_email'))

        try:
            validators.validate_password(password=password)
        except ValidationError as e:
            raise serializers.ValidationError({'password': list(e.messages)})

        if not user.is_active:
            raise serializers.ValidationError(self.default_error_messages.get('credentials'))

        # `not user.password` : distingue un compte jamais activé (mot de passe vide, migré depuis
        # un document CouchDB `eadls` sans `representative.password`) d'un compte déjà enregistré
        # (hash pbkdf2_sha256 réel) — empêche de réutiliser l'inscription pour réinitialiser un
        # mot de passe existant. Même critère que dashboard/authentication/forms.py (Phase 3).
        if user.password:
            raise serializers.ValidationError(self.default_error_messages.get('duplicated_email'))

        errors = dict()
        try:
            validators.validate_password(password=password)
        except ValidationError as e:
            errors['password'] = list(e.messages)

        if errors:
            raise serializers.ValidationError(errors)

        validation_code = attrs.get('validation_code')
        if validation_code != get_validation_code(user.email):
            raise serializers.ValidationError(self.default_error_messages.get('wrong_validation_code'))

        if not user.administrative_level:
            raise serializers.ValidationError(self.default_error_messages.get('no_administrative_level_affected'))

        user.password = make_password(password)
        user.save(update_fields=['password'])

        attrs['doc_id'] = str(user.id)
        attrs['eadl'] = _facilitator_to_legacy_dict(user)
        return attrs


class ADLActiveResponseSerializer(serializers.Serializer):
    is_active = serializers.BooleanField()
