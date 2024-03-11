from django.conf import settings
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from issue.serializers import SaveIssueDatasSerializer
from client import get_db, update_cloudant_document


COUCHDB_GRM_DATABASE = settings.COUCHDB_GRM_DATABASE

class SaveIssueDatas(APIView):
    throttle_classes = ()
    permission_classes = ()
    serializer_class = SaveIssueDatasSerializer
    

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)

        grm_db = get_db(COUCHDB_GRM_DATABASE)
        user_id = serializer.validated_data['user_id']
        has_error = False
        created = False
        
        for issue in serializer.validated_data['issues']:
            # if issue['reporter']['id'] == user_id:
            #     try:
            #         issue_id = issue['_id']
            #         issue_doc = grm_db[issue_id]
            #     except Exception:
            #         issue = grm_db.create_document(issue)

            # if issue['assignee']['id'] == user_id:
            #     try:
            #         issue_id = issue['_id']
            #         issue_doc = grm_db[issue_id]
            #         try:
            #             for k, v in issue.items():
            #                 issue_doc[k] = v
                            
            #             del issue_doc['_id']
            #             grm_db[issue_id] = issue_doc
            #             grm_db[issue_id].save()
            #         except Exception as exc:
            #             has_error = True
            #     except Exception:
            #         pass
            created = False
            if issue['reporter']['id'] == user_id:
                try:
                    issue_id = issue['_id']
                    issue_doc = grm_db[issue_id]
                except Exception:
                    issue = grm_db.create_document(issue)
                    created = True

            if not created and 'assignee' in issue and 'id' in issue['assignee'] and issue['assignee']['id'] == user_id:
                try:
                    issue_id = issue['_id']
                    issue_doc = grm_db[issue_id]
                    latest_revision = grm_db.get(issue_id)['_rev']
                    try:
                        del issue['_id']
                        del issue['_rev']
                        for k, v in issue.items():
                            if v or v == False or v == 0:
                                issue_doc[k] = v
                        issue_doc['_rev'] = latest_revision
                        issue_doc.save()
                    except Exception as exc:
                        print(exc)
                        has_error = True
                except Exception as exc:
                    print(exc)
                    pass
            
                
        
        return Response({'status': 'ok', 'has_error': has_error}, status=status.HTTP_200_OK)
