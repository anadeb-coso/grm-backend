from django.conf import settings
from prompt_toolkit import token
from rest_framework import serializers
from django.contrib.auth.models import User
from django.db.models import Q
from django.contrib.auth.hashers import check_password
from django.utils.translation import gettext_lazy as _


#Login User Serialization
class CheckUserSerializer(serializers.Serializer):
    username = serializers.CharField(required=False)
    password = serializers.CharField(required=False)
    token = serializers.CharField(required=False)

    def validate(self, data):
        username = data.get('username')
        password = data.get('password')
        token = data.get('token')

        if not username and not token:
            raise serializers.ValidationError(_("Username or token is required"))
        if not password and not token:
            raise serializers.ValidationError(_("Password is required"))

        if token:
            if token != settings.GRM_SECRET_KEY_GENRATE:
                raise serializers.ValidationError(_("Invalid token"))
            else:
                return True

        user = User.objects.filter(Q(email=username) | Q(username=username)).first()

        if user and check_password(password, user.password):
            if not user.is_active:
                raise serializers.ValidationError(_("Your account is inactive"))
            return user

        raise serializers.ValidationError(_("Incorrect credentials. If you have recently changed your password on one of our platforms, we recommend that you log out and log back in to that application. Thanks!"))