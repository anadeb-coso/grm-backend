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
import time

from attachments.serializers import (
    AttachmentUpdateStatusSerializer, IssueFileSerializer,
    TaskFileSerializer
)
from client import (
    COUCHDB_ATTACHMENT_DATABASE, COUCHDB_PASSWORD, COUCHDB_URL, COUCHDB_USERNAME, 
    get_db, upload_file, upload_file_s3
)
from attachments.functions import reduce_image_size
from grm.functions import compress_image

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
        print(data.get('doc_id'))
        if data.get('doc_id'):
            try:
                doc = grm_db[data['doc_id']]
            except Exception:
                raise Http404
            attachments = doc['attachments'] if 'attachments' in doc else list()
            
            if 'file' in data:
                file = data['file']
                # if file and file.content_type and 'image' in str(file.content_type).lower():
                #     file = compress_image(file, 0.7 if file.size > (1 * 1024 * 1024) else (0.5 if file.size > (0.5 * 1024 * 1024) else (file.size/(1024 * 1024))))
                
                if file:
                    for attachment in attachments:
                        if attachment['id'] == data['attachment_id'] and not attachment.get('uploaded'):
                            # file = data['file']
                            
                            """CouchDB"""
                            response = upload_file(file, COUCHDB_GRM_ATTACHMENT_DATABASE)
                            attachment['url'] = f'/grm_attachments/{response["id"]}/{file.name}'
                            attachment['uploaded'] = True
                            attachment['bd_id'] = response["id"]
                            doc.save()
                            return Response(response, status=201)
                            
                            
                            """S3"""
                            # file_url = upload_file_s3(file)
                            # # print(file_url)
                            # if file_url:
                            #     attachment['url'] = file_url
                            #     attachment['uploaded'] = True
                            #     attachment['bd_id'] = str(int(time.time()))
                            #     doc.save()
                            
                            #     return Response({
                            #                 'status': 201,
                            #                 'fileUrl': file_url,
                            #             }, status=201)
                    
                    reasons = doc['reasons'] if 'reasons' in doc else list()
                    resolution_files = doc['resolution_files'] if 'resolution_files' in doc else list()
                    escalation_reasons = doc['escalation_reasons'] if 'escalation_reasons' in doc else list()
                    for reason in reasons:
                        if reason['id'] == data['attachment_id'] and reason.get('type') and reason['type'] == 'file' and not reason.get('uploaded'):
                            # file = data['file']
                            
                            """CouchDB"""
                            response = upload_file(file, COUCHDB_GRM_ATTACHMENT_DATABASE)
                            reason['url'] = f'/grm_attachments/{response["id"]}/{file.name}'
                            reason['uploaded'] = True
                            reason['bd_id'] = response["id"]
                            
                            """S3"""
                            # file_url = upload_file_s3(file)
                            # # print(file_url)
                            # if file_url:
                            #     reason['url'] = file_url
                            #     reason['uploaded'] = True
                            #     reason['bd_id'] = str(int(time.time()))
                                

                            for r_file in resolution_files:
                                if r_file.get('id') == reason.get('id'):
                                    
                                    """CouchDB"""
                                    r_file['url'] = f'/grm_attachments/{response["id"]}/{file.name}'
                                    r_file['uploaded'] = True
                                    r_file['bd_id'] = response["id"]
                                    
                                    """S3"""
                                    # r_file['url'] = file_url
                                    # r_file['uploaded'] = True
                                    # r_file['bd_id'] = reason['bd_id']
                            
                            for e_file in escalation_reasons:
                                if e_file.get('attachment') and e_file.get('attachment').get('id') == reason.get('id'):
                                    
                                    """CouchDB"""
                                    e_file['attachment']['url'] = f'/grm_attachments/{response["id"]}/{file.name}'
                                    e_file['attachment']['uploaded'] = True
                                    e_file['attachment']['bd_id'] = response["id"]
                                    
                                    """S3"""
                                    # e_file['attachment']['url'] = file_url
                                    # e_file['attachment']['uploaded'] = True
                                    # e_file['attachment']['bd_id'] = reason['bd_id']

                            doc.save()
                            
                            """CouchDB"""
                            return Response(response, status=201)
                        
                            """S3"""
                            # return Response({
                            #             'status': 201,
                            #             'fileUrl': file_url,
                            #         }, status=201)
        else:
            print(data)
            if 'file' in data:
                file = data['file']
                # if file and file.content_type and 'image' in str(file.content_type).lower():
                #     file = compress_image(file, 0.7 if file.size > (1 * 1024 * 1024) else (0.5 if file.size > (0.5 * 1024 * 1024) else (file.size/(1024 * 1024))))
                
                if file:
                    response = upload_file(file, COUCHDB_GRM_ATTACHMENT_DATABASE)
                    print(response)
                    return Response({
                        'message': 'OK',
                        'fileUrl': f'/grm_attachments/{response["id"]}/{file.name}',
                        'bd_id': response["id"],
                        'response': response
                    }, status=201)
                        
        raise Http404
