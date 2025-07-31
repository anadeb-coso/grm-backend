from django.conf import settings
from django.http import Http404
from drf_yasg.openapi import IN_QUERY, Parameter
from drf_yasg.utils import swagger_auto_schema
from rest_framework import generics, parsers, renderers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from authentication import ADL, MAJOR
from authentication.serializers import (
    ADLActiveResponseSerializer, CredentialSerializer, RegisterSerializer,
    UserAuthSerializer
)
from client import get_db


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
            'username': settings.COUCHDB_USERNAME,
            'password': settings.COUCHDB_PASSWORD,
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
            'username': settings.COUCHDB_USERNAME,
            'password': settings.COUCHDB_PASSWORD,
            'doc_id': serializer.validated_data['doc_id'],
            'eadl': serializer.validated_data['eadl']
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
        selector = {
            "representative.email": email,
            "type": {"$in": [ADL, MAJOR]}
        }
        eadl_db = get_db()
        docs = eadl_db.get_query_result(selector)
        try:
            doc = eadl_db[docs[0][0]['_id']]
        except Exception:
            raise Http404

        is_active = doc['representative']['is_active'] if 'representative' in doc and 'is_active' in doc[
            'representative'] else False

        reponse_data = {'is_active': is_active}
        reponse_serializer = ADLActiveResponseSerializer(data=reponse_data)
        reponse_serializer.is_valid(raise_exception=True)
        return Response(reponse_data, status=status.HTTP_200_OK)
