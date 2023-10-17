from django.contrib.auth.hashers import check_password
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from authentication.models import User


class SaveIssueDatasSerializer(serializers.Serializer):
    issues = serializers.JSONField()
    email = serializers.JSONField()

    default_error_messages = {
        'invalid': _('Invalid data. Expected a dictionary, but got {datatype}.'),
        'credentials': _('Unable to log in with provided credentials.'),
    }

    def validate(self, attrs):
        email = attrs.get('email')

        if email:
            user = User.objects.filter(email=email).first()
            if not user:
                msg = self.default_error_messages['credentials']
                raise serializers.ValidationError(msg, code='authorization')
        else:
            msg = _('Must include "username" and "password".')
            raise serializers.ValidationError(msg, code='authorization')

        attrs['email'] = email
        attrs['user_id'] = user.id
        return attrs
