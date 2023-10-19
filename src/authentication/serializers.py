import django.contrib.auth.password_validation as validators
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from authentication import ADL, MAJOR
from authentication.utils import get_validation_code
from client import get_db
from authentication.models import User


class CredentialSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField()
    doc_id = serializers.CharField()


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

        selector = {
            "$and": [
                {
                    "representative.email": {"$eq": email}
                },
                {
                    "representative.is_active": {"$eq": True}
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
        try:
            doc = eadl_db[docs[0][0]['_id']]
        except Exception:
            raise serializers.ValidationError(self.default_error_messages.get('credentials'))

        if email and password:
            if not doc or not check_password(password, doc['representative']['password']):
                msg = self.default_error_messages['credentials']
                raise serializers.ValidationError(msg, code='authorization')
        else:
            msg = _('Must include "email" and "password".')
            raise serializers.ValidationError(msg, code='authorization')

        attrs['doc_id'] = doc['_id'] if '_id' in doc else None
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
        except User.DoesNotExist as exc:
            raise serializers.ValidationError(self.default_error_messages.get('not_found_email'))
        
        try:
            validators.validate_password(password=password)
        except ValidationError as e:
            raise serializers.ValidationError({'password': list(e.messages)})

        selector = {
            "$and": [
                {
                    "representative.email": email
                },
                {
                    "representative.is_active": {"$eq": True}
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
        try:
            doc = eadl_db[docs[0][0]['_id']]
        except Exception:
            raise serializers.ValidationError(self.default_error_messages.get('credentials'))

        # prevents the sign up is used to reset password
        if 'password' in doc['representative'] and doc['representative']['password']:
            raise serializers.ValidationError(self.default_error_messages.get('duplicated_email'))

        errors = dict()
        try:
            # validate the password and catch the exception
            validators.validate_password(password=password)

        # the exception raised here is different than serializers.ValidationError
        except ValidationError as e:
            errors['password'] = list(e.messages)

        if errors:
            raise serializers.ValidationError(errors)

        validation_code = attrs.get('validation_code')

        if validation_code != get_validation_code(doc['representative']['email']):
            raise serializers.ValidationError(self.default_error_messages.get('wrong_validation_code'))
        
        if not user.administrative_level:
            raise serializers.ValidationError(self.default_error_messages.get('no_administrative_level_affected'))
        
        doc['representative']['password'] = make_password(password)
        doc.save()

        user.password = doc['representative']['password']
        user.save()

        attrs['doc_id'] = doc['_id'] if '_id' in doc else None
        return attrs


class ADLActiveResponseSerializer(serializers.Serializer):
    is_active = serializers.BooleanField()
