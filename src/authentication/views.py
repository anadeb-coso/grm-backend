from django.http import Http404
from drf_yasg.openapi import IN_QUERY, Parameter
from drf_yasg.utils import swagger_auto_schema
from rest_framework import generics, parsers, renderers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from authentication.models import User
from authentication.serializers import (
    ADLActiveResponseSerializer, CredentialSerializer, RegisterSerializer,
    UserAuthSerializer, _facilitator_to_legacy_dict
)


class RegisterAPIView(APIView):
    throttle_classes = ()
    permission_classes = ()
    parser_classes = (parsers.FormParser, parsers.MultiPartParser, parsers.JSONParser,)
    renderer_classes = (renderers.JSONRenderer,)
    serializer_class = RegisterSerializer

    def get_serializer_context(self):
        return {
            'request': self.request,
            'format': self.format_kwarg,
            'view': self
        }

    def get_serializer(self, *args, **kwargs):
        kwargs['context'] = self.get_serializer_context()
        return self.serializer_class(*args, **kwargs)

    @swagger_auto_schema(
        request_body=RegisterSerializer(),
        responses={201: CredentialSerializer()},
        operation_description="Allowed user types: adl or major"
    )
    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)

        credentials = {
            'doc_id': serializer.validated_data['doc_id'],
            'eadl': serializer.validated_data['eadl']
        }
        credential_serializer = CredentialSerializer(data=credentials)
        credential_serializer.is_valid(raise_exception=True)
        return Response(credential_serializer.data, status=status.HTTP_201_CREATED)


class AuthenticateAPIView(RegisterAPIView):
    serializer_class = UserAuthSerializer

    @swagger_auto_schema(
        request_body=UserAuthSerializer(),
        responses={200: CredentialSerializer()},
        operation_description="Allowed user types: adl or major"
    )
    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)

        credentials = {
            'doc_id': serializer.validated_data['doc_id'],
            'eadl': serializer.validated_data['eadl']
        }
        credential_serializer = CredentialSerializer(data=credentials)
        credential_serializer.is_valid(raise_exception=True)
        return Response(credential_serializer.data, status=status.HTTP_200_OK)


class MyProfileAPIView(generics.GenericAPIView):
    """Profil (forme legacy `eadl`) de l'utilisateur authentifié par JWT — remplace, pour les
    clients déjà connectés, l'appel à `obtain-auth-credentials` qui obligeait le mobile à
    renvoyer le mot de passe en clair à chaque rafraîchissement du profil (ex. à chaque étape du
    formulaire de plainte). Le token d'accès suffit désormais : `request.user` est résolu par
    `JWTAuthentication` (cf. `REST_FRAMEWORK['DEFAULT_AUTHENTICATION_CLASSES']`)."""
    permission_classes = (IsAuthenticated,)

    @swagger_auto_schema(
        responses={200: CredentialSerializer()},
        operation_description="Profil de l'utilisateur authentifié (JWT), forme legacy eadl."
    )
    def get(self, request, *args, **kwargs):
        credentials = {
            'doc_id': str(request.user.id),
            'eadl': _facilitator_to_legacy_dict(request.user),
        }
        credential_serializer = CredentialSerializer(data=credentials)
        credential_serializer.is_valid(raise_exception=True)
        return Response(credential_serializer.data, status=status.HTTP_200_OK)


class ADLActiveAPIView(generics.GenericAPIView):

    @swagger_auto_schema(
        responses={200: ADLActiveResponseSerializer()},
        operation_description="Get adl user status",
        manual_parameters=[
            Parameter('email', IN_QUERY, description='Email of an facilitator user', type='string')
        ]
    )
    def get(self, request, *args, **kwargs):
        email = request.GET.get('email')
        user = User.objects.filter(email=email).first()
        if not user:
            raise Http404

        reponse_data = {'is_active': user.is_active}
        reponse_serializer = ADLActiveResponseSerializer(data=reponse_data)
        reponse_serializer.is_valid(raise_exception=True)
        return Response(reponse_data, status=status.HTTP_200_OK)
