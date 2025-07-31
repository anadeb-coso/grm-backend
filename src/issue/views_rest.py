from django.conf import settings
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.utils.translation import gettext_lazy as _

from issue.serializers import SaveIssueDatasSerializer, CheckSyncIssuesSerializer
from client import get_db, update_cloudant_document
from dashboard.tasks import check_issues, send_sms_message, escalate_issues, send_a_new_issue_notification


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
        send_message = False

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
                            if k not in ('publish', 'notification_send') and (v or v == False or v == 0):
                                if k in issue_doc and issue_doc[k] != v:
                                    send_message = True

                                issue_doc[k] = v
                        issue_doc['_rev'] = latest_revision
                        issue_doc.save()
                    except Exception as exc:
                        print(exc)
                        has_error = True
                except Exception as exc:
                    print(exc)
                    pass
            
                
        check_issues()
        escalate_issues()
        send_sms_message()
        send_a_new_issue_notification()

        return Response({
            'status': 'ok', 
            'has_error': has_error, 
            'message': _("During this update, we noticed that some data had been stored locally on your phone but were not automatically synced during yours recordings. We want to assure you that this issue has now been resolved. To ensure proper automatic syncing in the future, please clear the MGP app's storage data via your phone settings, or uninstall and reinstall the app.") if send_message else None
            }, status=status.HTTP_200_OK)




class CheckSyncIssues(APIView):
    throttle_classes = ()
    permission_classes = ()
    serializer_class = CheckSyncIssuesSerializer
    

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)

        check_issues()
        escalate_issues()
        send_sms_message()
        send_a_new_issue_notification()
        
        
        return Response({'status': 'ok'}, status=status.HTTP_200_OK)