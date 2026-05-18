from django.conf import settings
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.utils.translation import gettext_lazy as _
from datetime import datetime, timedelta

from issue.serializers import SaveIssueDatasSerializer, CheckSyncIssuesSerializer
from client import get_db, update_cloudant_document
from dashboard.tasks import check_issues, send_sms_message, escalate_issues, send_a_new_issue_notification
from authentication.api.auth.login import CheckUserSerializer
from grm.utils import get_administrative_level_descendants_using_mis
from grm.api.custom import CustomPagination
from grm.call_objects_from_other_db import mis_objects_call
from administrativelevels.models import AdministrativeLevel


COUCHDB_GRM_DATABASE = settings.COUCHDB_GRM_DATABASE
COUCHDB_DATABASE_ADMINISTRATIVE_LEVEL = settings.COUCHDB_DATABASE_ADMINISTRATIVE_LEVEL

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
    



class RestGetIssues(APIView):
    throttle_classes = ()
    permission_classes = ()
    serializer_class = CheckUserSerializer
    
    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data
        
        grm_db = get_db(COUCHDB_GRM_DATABASE)
        adl_db = get_db(COUCHDB_DATABASE_ADMINISTRATIVE_LEVEL)
        
        start_date = request.data.get('start_date')
        end_date = request.data.get('end_date')
        code = request.data.get('code')
        assigned_to = request.data.get('assigned_to')
        category = request.data.get('category')
        status = request.data.get('status')
        other = request.data.get('other')
        region = request.data.get('region')
        region_name = request.data.get('region_name')
        region_parent_name = request.data.get('region_parent_name')
        reported_by = request.data.get('reported_by')
        publish = request.data.get('publish')
        user = request.user

        if user.groups.filter(name__in=["Admin", "ViewerOfAllIssues"]).exists():
            selector = {
                "type": "issue",
                "confirmed": True,
                "auto_increment_id": {"$ne": ""},
                "created_date": {"$exists": True},
            }
        else:
            selector = {
                "type": "issue",
                "confirmed": True,
                "auto_increment_id": {"$ne": ""},
                "created_date": {"$exists": True},
            }
            
            if hasattr(user, 'governmentworker') and user.governmentworker.administrative_id != "1":
                parent_ids = user.governmentworker.all_administrative_ids
                
                descendants = []
                for p_id in parent_ids:
                    descendants += get_administrative_level_descendants_using_mis(adl_db, p_id, [], self.request.user)
                allowed_regions = descendants + parent_ids

                selector["$or"] = [
                    {"assignee.id": user.id},
                    {"$and": [
                        {"category.assigned_department": user.governmentworker.department},
                        {"administrative_region.administrative_id": {"$in": allowed_regions + [int(elt) for elt in allowed_regions if isinstance(elt, str) and elt.isdigit() and int(elt) not in allowed_regions]}},
                    ]}
                ]
            else:
                selector = {
                    "type": "issue",
                    "publish": True,
                    "confirmed": True,
                    "auto_increment_id": {"$ne": ""},
                }

        date_range = {}
        if start_date:
            start_date = datetime.strptime(start_date, '%d/%m/%Y').strftime('%Y-%m-%dT%H:%M:%S.%fZ')
            date_range["$gte"] = start_date
            selector["intake_date"] = date_range
        if end_date:
            end_date = (datetime.strptime(end_date, '%d/%m/%Y') + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
            date_range["$lte"] = end_date
            selector["intake_date"] = date_range
        if code:
            code_filter = {"$regex": f"(?i){code}"} #{"$regex": f"^{code}"}
            selector['$or'] = [{"internal_code": code_filter}, {"tracking_code": code_filter},
                               {"description": code_filter}]
        if assigned_to:
            selector["assignee.id"] = int(assigned_to)
        if category:
            selector["category.id"] = int(category)
        if status:
            selector["status.id"] = int(status)
        if other:
            if other == "Escalate":
                selector["escalation_reasons"] = {"$exists": True}
        if reported_by:
            selector["reporter.id"] = int(reported_by)
        if publish in ('True', 'False'):
            selector["publish"] = True if publish == 'True' else False

        if region or region_name:
            filter_regions = []
            if region_name:
                if region_parent_name:
                    adl_object = mis_objects_call.filter_objects(
                        AdministrativeLevel,
                        name=region_name,
                        parent__name=region_parent_name
                    ).first()
                else:
                    adl_object = mis_objects_call.filter_objects(
                        AdministrativeLevel,
                        name=region_name,
                    ).first()
                if adl_object:
                    filter_regions = get_administrative_level_descendants_using_mis(adl_db, adl_object.id, [], self.request.user) + [str(adl_object.id)]
            else:
                filter_regions = get_administrative_level_descendants_using_mis(adl_db, region, [], self.request.user) + [region]

            selector["administrative_region.administrative_id"] = {
                "$in": filter_regions + [int(elt) for elt in filter_regions if isinstance(elt, str) and elt.isdigit() and int(elt) not in filter_regions]
            }
        
        queryset = list(grm_db.get_query_result(selector, sort=[{'created_date': 'desc'}]))
        
        paginator = CustomPagination()
        paginated_data = paginator.paginate_queryset(queryset, request)

        return paginator.get_paginated_response(paginated_data)