import requests
from django.conf import settings
from django.http import Http404, HttpResponse
from drf_yasg.openapi import IN_QUERY, Parameter
from drf_yasg.utils import swagger_auto_schema
from rest_framework import generics, parsers
from rest_framework.response import Response
# from storages.backends.s3boto3 import S3Boto3Storage
import os
from datetime import datetime

from attachments.serializers import (
    AttachmentUpdateStatusSerializer, IssueFileSerializer,
    TaskFileSerializer
)
from client import COUCHDB_ATTACHMENT_DATABASE, COUCHDB_PASSWORD, COUCHDB_URL, COUCHDB_USERNAME, get_db, upload_file
from attachments.functions import reduce_image_size

COUCHDB_GRM_DATABASE = settings.COUCHDB_GRM_DATABASE
COUCHDB_GRM_ATTACHMENT_DATABASE = settings.COUCHDB_GRM_ATTACHMENT_DATABASE


class GetAttachmentAPIView(generics.GenericAPIView):

    @swagger_auto_schema(
        manual_parameters=[
            Parameter(
                'db',
                IN_QUERY,
                description='Keyword to choose the database to use (keyword: grm). If the parameter is not passed or '
                            'is passed empty then it is used by default in the attachment database for Participatory '
                            'Budgeting.',
                type='string'
            )
        ]
    )
    def get(self, request, *args, **kwargs):
        db = request.GET.get('db', '')
        if db == 'grm':
            db = COUCHDB_GRM_ATTACHMENT_DATABASE
        else:
            db = COUCHDB_ATTACHMENT_DATABASE
        url = f'{COUCHDB_URL}/{db}/{kwargs["id"]}/{kwargs["name"]}'
        response = requests.get(url, auth=(COUCHDB_USERNAME, COUCHDB_PASSWORD))
        return HttpResponse(
            content=response.content,
            status=response.status_code,
            content_type=response.headers['Content-Type']
        )


class UploadTaskAttachmentAPIView(generics.GenericAPIView):
    serializer_class = TaskFileSerializer
    parser_classes = (parsers.FormParser, parsers.MultiPartParser)

    @staticmethod
    def get_task_attachments(doc, phase, task):
        attachments = list()
        try:
            attachments = doc['phases'][phase - 1]['tasks'][task - 1]['attachments']
        except Exception:
            pass
        return attachments

    @swagger_auto_schema(
        responses={201: AttachmentUpdateStatusSerializer()},
        operation_description="Allowed file size less than or equal to 2 MB"
    )
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        eadl_db = get_db()
        try:
            doc = eadl_db[data['doc_id']]
        except Exception:
            raise Http404
        attachments = self.get_task_attachments(doc, data['phase'], data['task'])
        for attachment in attachments:
            if attachment['id'] == data['attachment_id']:
                response = upload_file(data['file'])
                attachment['url'] = f'/attachments/{response["id"]}/{data["file"].name}'
                attachment['uploaded'] = True
                doc.save()
                return Response(response, status=201)
        raise Http404


class UploadIssueAttachmentAPIView(generics.GenericAPIView):
    serializer_class = IssueFileSerializer
    parser_classes = (parsers.FormParser, parsers.MultiPartParser)

    @swagger_auto_schema(
        responses={201: AttachmentUpdateStatusSerializer()},
        operation_description="Allowed file size less than or equal to 2 MB"
    )
    def post(self, request, *args, **kwargs):
        # serializer = self.get_serializer(data=request.data)
        # serializer.is_valid(raise_exception=True)
        data = request.data #serializer.validated_data
        grm_db = get_db(COUCHDB_GRM_DATABASE)
        try:
            doc = grm_db[data['doc_id']]
        except Exception:
            raise Http404
        attachments = doc['attachments'] if 'attachments' in doc else list()
        for attachment in attachments:
            if attachment['id'] == data['attachment_id'] and not attachment.get('uploaded'):
                file = data['file']
                # if 'image' in file.content_type or 'img' in file.content_type:
                #     try:
                #         file = reduce_image_size(file)
                #     except:
                #         file = file
                # try:
                #     #S3
                #     file_directory_within_bucket = 'proof_of_work/'
                #     file_path_within_bucket = os.path.join(
                #         file_directory_within_bucket,
                #         file.name
                #     )

                #     media_storage = S3Boto3Storage()

                #     if not media_storage.exists(file_path_within_bucket):  # avoid overwriting existing file
                #         media_storage.save(file_path_within_bucket, file)
                #         file_url = media_storage.url(file_path_within_bucket)

                #         attachment['url'] = file_url
                #         attachment['uploaded'] = True
                #         attachment['bd_id'] = datetime.now().strftime('%Y-%m-%dT%H:%M:%S.%fZ')
                #         doc.save()
                #         return Response({
                #             'message': 'OK',
                #             'fileUrl': file_url,
                #         }, status=201)
                #     #End S3
                # except:
                response = upload_file(file, COUCHDB_GRM_ATTACHMENT_DATABASE)
                attachment['url'] = f'/grm_attachments/{response["id"]}/{file.name}'
                attachment['uploaded'] = True
                attachment['bd_id'] = response["id"]
                doc.save()
                return Response(response, status=201)
        
        reasons = doc['reasons'] if 'reasons' in doc else list()
        resolution_files = doc['resolution_files'] if 'resolution_files' in doc else list()
        escalation_reasons = doc['escalation_reasons'] if 'escalation_reasons' in doc else list()
        for reason in reasons:
            if reason['id'] == data['attachment_id'] and reason.get('type') and reason['type'] == 'file' and not reason.get('uploaded'):
                file = data['file']
                # if 'image' in file.content_type or 'img' in file.content_type:
                #     try:
                #         file = reduce_image_size(file)
                #     except:
                #         file = file
                # response = upload_file(file, COUCHDB_GRM_ATTACHMENT_DATABASE)
                # reason['url'] = f'/grm_attachments/{response["id"]}/{file.name}'
                # reason['uploaded'] = True
                # reason['bd_id'] = response["id"]
                # doc.save()
                # return Response(response, status=201)
                # try:
                #     #S3
                #     file_directory_within_bucket = 'proof_of_work/'
                #     file_path_within_bucket = os.path.join(
                #         file_directory_within_bucket,
                #         file.name
                #     )

                #     media_storage = S3Boto3Storage()

                #     if not media_storage.exists(file_path_within_bucket):  # avoid overwriting existing file
                #         media_storage.save(file_path_within_bucket, file)
                #         file_url = media_storage.url(file_path_within_bucket)

                #         attachment['url'] = file_url
                #         attachment['uploaded'] = True
                #         attachment['bd_id'] = datetime.now().strftime('%Y-%m-%dT%H:%M:%S.%fZ')
                #         doc.save()
                #         return Response({
                #             'message': 'OK',
                #             'fileUrl': file_url,
                #         }, status=201)
                #     #End S3
                # except:
                response = upload_file(file, COUCHDB_GRM_ATTACHMENT_DATABASE)
                reason['url'] = f'/grm_attachments/{response["id"]}/{file.name}'
                reason['uploaded'] = True
                reason['bd_id'] = response["id"]

                for r_file in resolution_files:
                    if r_file.get('id') == reason.get('id'):
                        r_file['url'] = f'/grm_attachments/{response["id"]}/{file.name}'
                        r_file['uploaded'] = True
                        r_file['bd_id'] = response["id"]
                
                for e_file in escalation_reasons:
                    if e_file.get('attachment') and e_file.get('attachment').get('id') == reason.get('id'):
                        e_file['attachment']['url'] = f'/grm_attachments/{response["id"]}/{file.name}'
                        e_file['attachment']['uploaded'] = True
                        e_file['attachment']['bd_id'] = response["id"]

                doc.save()
                return Response(response, status=201)
            
        raise Http404
