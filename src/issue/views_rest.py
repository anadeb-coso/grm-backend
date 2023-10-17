from django.conf import settings
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from issue.serializers import SaveIssueDatasSerializer
from client import get_db


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
        for issue in serializer.validated_data['issues']:
            if issue['reporter']['id'] == user_id or issue['assignee']['id'] == user_id:
                issue_id = issue['_id']
                _pass = False
                try:
                    issue_doc = grm_db[issue_id]
                except Exception:
                    grm_db.create_document(issue)
                    _pass = True

                if not _pass:
                    # Save doc
                    try:
                        for k, v in issue.items():
                            issue_doc[k] = v

                        issue_doc.save()
                    except Exception as exc:
                        has_error = True
        
        return Response({'status': 'ok', 'has_error': has_error, 'save_new': _pass}, status=status.HTTP_200_OK)
