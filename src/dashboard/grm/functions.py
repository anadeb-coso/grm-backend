from django.utils.translation import gettext_lazy as _
from datetime import datetime, timedelta
from django.conf import settings
import pandas as pd
import os
from sys import platform

from grm.utils import datetime_str
from grm.my_librairies.mail.send_mail import send_email
from grm.constants import (
    SAFEGUARD_SPECIALIST_EMAILS, OTHER_SPECIALIST_ON_MAIL_COPY, ANADEB_EMAILS_ON_COPY,
    OTHERS_EMAILS_ON_COPY, ASSISTANTS_SAFEGUARD_SPECIALIST_EMAILS, COORDINATORS_EMAILS_ON_COPY
)
from administrativelevels.models import AdministrativeLevel
from grm.my_librairies.functions import strip_accents
from grm.call_objects_from_other_db import mis_objects_call
from client import get_db
from grm.utils import get_administrative_level_descendants_using_mis


COUCHDB_GRM_DATABASE = settings.COUCHDB_GRM_DATABASE
COUCHDB_DATABASE_ADMINISTRATIVE_LEVEL = settings.COUCHDB_DATABASE_ADMINISTRATIVE_LEVEL

def get_issue_status_stories(user, doc, status):
    issue_status_stories = doc["issue_status_stories"] if doc.get("issue_status_stories") else []
    
    issue_status_stories.insert(0, {
        'status': status,
        'user': {
            'id': user.id,
            'username': user.username,
            'full_name': user.get_full_name()
        },
        "comment": doc.get('_comment'),
        'datetime': datetime_str()
    })

    return issue_status_stories



def send_notification_by_mail(issue):
    try:
        return send_email(
            f"{_('COSO GRM - A new issue recorded')} - {issue['tracking_code']} | {issue['internal_code']}",
            "mail/send/comment",
            {
                "datas": {
                    _("Title"): _("COSO GRM - A new issue recorded"),
                    _("Code"): issue['tracking_code'],
                    _("Category"): issue['category']['name'],
                    _("Description"): issue['description'],
                    _("Date of incident/complaint"): issue.get('issue_date'),
                    _("Date of registration"): issue.get('created_date'),
                    _("Level"): issue['category']['administrative_level'],
                    _("Source"): issue['source'],
                },
                "user": {
                    _("Reporter"): issue['reporter']['name']
                },
                "url": f"http://grm-2-env.eba-speiyafz.us-west-1.elasticbeanstalk.com/fr/grm/issue-detail/{issue['auto_increment_id']}/"
            },
            SAFEGUARD_SPECIALIST_EMAILS,
            cc= COORDINATORS_EMAILS_ON_COPY + ASSISTANTS_SAFEGUARD_SPECIALIST_EMAILS + OTHER_SPECIALIST_ON_MAIL_COPY + ANADEB_EMAILS_ON_COPY + OTHERS_EMAILS_ON_COPY
        )
    except:
        return None

def send_notification_on_escalation_by_mail(issue):
    try:
        return send_email(
            f"{_('COSO GRM - A new issue scaled')} - {issue['tracking_code']} | {issue['internal_code']}",
            "mail/send/comment",
            {
                "datas": {
                    _("Title"): _("COSO GRM - A new issue scaled"),
                    _("Code"): issue['tracking_code'],
                    _("Category"): issue['category']['name'],
                    _("Description"): issue['description'],
                    _("Up to level"): issue['escalation_administrativelevels'][0]['escalate_to']['administrative_level'],
                    _("Comment on the unresolution"): issue['unresolved_reason'],
                    _("Unresolution date"): datetime.strptime(issue['unresolved_date'], "%Y-%m-%dT%H:%M:%S.%fZ"),
                    _("Comments on the scalation"): issue['escalate_reason'],
                    _("Scalation date"): datetime.strptime(issue['escalate_date'], "%Y-%m-%dT%H:%M:%S.%fZ")
                },
                "user": {
                    _("Assigned to"): issue['assignee']['name']
                },
                "url": f"http://grm-2-env.eba-speiyafz.us-west-1.elasticbeanstalk.com/fr/grm/issue-detail/{issue['auto_increment_id']}/"
            },
            SAFEGUARD_SPECIALIST_EMAILS,
            cc= COORDINATORS_EMAILS_ON_COPY + ASSISTANTS_SAFEGUARD_SPECIALIST_EMAILS + OTHER_SPECIALIST_ON_MAIL_COPY + ANADEB_EMAILS_ON_COPY + OTHERS_EMAILS_ON_COPY
        )
    except:
        return None



def send_assignee_notification_by_mail(issue, user):
    try:
        return send_email(
            f"{_('COSO GRM - You have been assigned a issue')} - {issue['tracking_code']} | {issue['internal_code']}",
            "mail/send/comment",
            {
                "datas": {
                    _("Title"): _("COSO GRM - You have been assigned a issue"),
                    _("Code"): issue['tracking_code'],
                    _("Category"): issue['category']['name'],
                    _("Description"): issue['description'],
                    _("Level"): issue['escalation_administrativelevels']['escalate_to']['administrative_level'] \
                        if 'escalation_administrativelevels' in issue and issue['escalation_administrativelevels'] else \
                            issue['category']['administrative_level'],
                    _("Source"): issue['source'],
                },
                "user": {
                    _("Reporter"): issue['reporter']['name'],
                    _("Assigned to"): issue['assignee']['name']
                },
                "user_full_name": f"{user.first_name} {user.last_name}",
                "comment":  _("Please find below the information concerning the new issue that has just been assigned to you."), 
                "greeting":  _("Hello"),
                "all_sex":  _("Mr./Mrs."),
                "url": f"http://grm-2-env.eba-speiyafz.us-west-1.elasticbeanstalk.com/fr/grm/issue-detail/{issue['auto_increment_id']}/"
            },
            [user.email],
            cc=ASSISTANTS_SAFEGUARD_SPECIALIST_EMAILS + OTHERS_EMAILS_ON_COPY
        )
    except:
        return None



def get_adminstrative_level_by_name(ad_name, canton_str: str):
    try:
        return mis_objects_call.get_object(AdministrativeLevel, name=ad_name, type="Village")
    except AdministrativeLevel.DoesNotExist as exc:
        try:
            return mis_objects_call.get_object(AdministrativeLevel, 
                name=strip_accents(ad_name), type="Village", parent__name=canton_str
            )
        except AdministrativeLevel.DoesNotExist as exc:
            try:
                return mis_objects_call.get_object(AdministrativeLevel, name=ad_name.replace(" ", ""), type="Village", parent__name=canton_str)
            except AdministrativeLevel.DoesNotExist as exc:
                try:
                    return mis_objects_call.get_object(AdministrativeLevel, 
                        name=strip_accents(ad_name.replace(" ", "")), type="Village", parent__name=canton_str
                    )
                except AdministrativeLevel.DoesNotExist as exc:
                    try:
                        return mis_objects_call.get_object(AdministrativeLevel, 
                            name=strip_accents(ad_name.replace("-", " ")), type="Village", parent__name=canton_str
                        )
                    except AdministrativeLevel.DoesNotExist as exc:
                        try:
                            return mis_objects_call.get_object(AdministrativeLevel, 
                                name=strip_accents(ad_name.replace(" ", "-")), type="Village", parent__name=canton_str
                            )
                        except AdministrativeLevel.DoesNotExist as exc:
                            try:
                                return mis_objects_call.get_object(AdministrativeLevel, 
                                    name=strip_accents(ad_name.replace(" ", "-")), type="Village", parent__name=canton_str
                                )
                            except AdministrativeLevel.DoesNotExist as exc:
                                return None
                            except AdministrativeLevel.MultipleObjectsReturned as exc:
                                return None
                        except AdministrativeLevel.MultipleObjectsReturned as exc:
                            return None
                    except AdministrativeLevel.MultipleObjectsReturned as exc:
                        return None
                
                except AdministrativeLevel.MultipleObjectsReturned as exc:
                    return None

            except AdministrativeLevel.MultipleObjectsReturned as exc:
                return None

        except AdministrativeLevel.MultipleObjectsReturned as exc:
            return None

    except AdministrativeLevel.MultipleObjectsReturned as exc:
        return None
    


def filter_adminstrative_level_by_name(ad_name, canton_str: str):
    _filters = None
    try:
        _filters = mis_objects_call.filter_objects(AdministrativeLevel, name=ad_name, type="Village")
    except AdministrativeLevel.DoesNotExist as exc:
        try:
            _filters = mis_objects_call.filter_objects(AdministrativeLevel, 
                name=strip_accents(ad_name), type="Village"
            )
        except AdministrativeLevel.DoesNotExist as exc:
            try:
                _filters = mis_objects_call.filter_objects(AdministrativeLevel, name=ad_name.replace(" ", ""), type="Village")
            except AdministrativeLevel.DoesNotExist as exc:
                try:
                    _filters = mis_objects_call.filter_objects(AdministrativeLevel, 
                        name=strip_accents(ad_name.replace(" ", "")), type="Village"
                    )
                except AdministrativeLevel.DoesNotExist as exc:
                    try:
                        _filters = mis_objects_call.filter_objects(AdministrativeLevel, 
                            name=strip_accents(ad_name.replace("-", " ")), type="Village"
                        )
                    except AdministrativeLevel.DoesNotExist as exc:
                        try:
                            _filters = mis_objects_call.filter_objects(AdministrativeLevel, 
                                name=strip_accents(ad_name.replace(" ", "-")), type="Village"
                            )
                        except AdministrativeLevel.DoesNotExist as exc:
                            try:
                                _filters = mis_objects_call.filter_objects(AdministrativeLevel, 
                                    name=strip_accents(ad_name.replace(" ", "-")), type="Village"
                                )
                            except AdministrativeLevel.DoesNotExist as exc:
                                _filters = None
                            except AdministrativeLevel.MultipleObjectsReturned as exc:
                                _filters = None
                        except AdministrativeLevel.MultipleObjectsReturned as exc:
                            _filters = None
                    except AdministrativeLevel.MultipleObjectsReturned as exc:
                        _filters = None
                
                except AdministrativeLevel.MultipleObjectsReturned as exc:
                    _filters = None

            except AdministrativeLevel.MultipleObjectsReturned as exc:
                _filters = None

        except AdministrativeLevel.MultipleObjectsReturned as exc:
            _filters = None

    except AdministrativeLevel.MultipleObjectsReturned as exc:
        _filters = None

    if _filters and _filters.count() > 1:
        for obj in _filters:
            if obj.parent and obj.parent.name == canton_str:
                return obj
    elif _filters:
        return _filters.first()
    
    return None




def export_issues(request):
    grm_db = get_db(COUCHDB_GRM_DATABASE)
    adl_db = get_db(COUCHDB_DATABASE_ADMINISTRATIVE_LEVEL)
    index = int(request.GET.get('index'))
    offset = int(request.GET.get('offset'))
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    code = request.GET.get('code')
    assigned_to = request.GET.get('assigned_to')
    category = request.GET.get('category')
    status = request.GET.get('status')
    other = request.GET.get('other')
    region = request.GET.get('region')
    reported_by = request.GET.get('reported_by')
    publish = request.GET.get('publish')
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
                descendants += get_administrative_level_descendants_using_mis(adl_db, p_id, [], request.user)
            allowed_regions = descendants + parent_ids

            selector["$or"] = [
                {"assignee.id": user.id},
                {"$and": [
                    {"category.assigned_department": user.governmentworker.department},
                    {"administrative_region.administrative_id": {"$in": allowed_regions}},
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

    if region:
        filter_regions = get_administrative_level_descendants_using_mis(adl_db, region, [], request.user) + [region]
        selector["administrative_region.administrative_id"] = {
            "$in": filter_regions
        }

    issues = grm_db.get_query_result(selector, sort=[{'created_date': 'desc'}])
    data = []

    def append_data_to_dict(flat_doc: dict, dict_item: tuple):
        if type(dict_item[1]) in (dict, list):
            if type(dict_item[1]) == dict:
                for k, v in dict_item[1].items():
                    append_data_to_dict(flat_doc, (f"{dict_item[0]}_{k}", v))
            else:
                for i in range(len(dict_item[1])):
                    append_data_to_dict(flat_doc, (f"{dict_item[0]}_{i}", dict_item[1][i]))
        else:
            flat_doc[dict_item[0]] = dict_item[1]

    for row in issues:
        # doc = row.get('doc', {})
        # flat_doc = {
        #     'ID': doc.get('_id', ''),
        #     'ID': doc.get('auto_increment_id', ''),
        #     'Code interne': doc.get('internal_code', ''),
        #     'Code de suivi': doc.get('tracking_code', ''),
        #     'Description': doc.get('description', ''),
        #     'Statut': doc.get('status', {}).get('name', ''),
        #     'Date de création': doc.get('created_date', ''),
        #     'Date de résolution': doc.get('resolution_date', ''),
        # }
        
        # # Concaténer les commentaires dans un champ
        # comments = doc.get('comments', [])
        # flat_doc['Commentaires'] = " | ".join([c.get('comment', '') for c in comments])
        
        # data.append(flat_doc)
        flat_doc = {}
        for k, v in row.items():
            append_data_to_dict(flat_doc, (k, v))

        data.append(flat_doc)

    df = pd.DataFrame(data)


    if not os.path.exists("media/grm"):
            os.makedirs("media/grm")
    file_path = f'grm/complaints_{str(datetime.today().replace(microsecond=0)).replace("-", "").replace(":", "").replace(" ", "_")}.xlsx'

    df = df.to_excel("media/"+file_path, sheet_name='Plaintes', index=False)

    # with pd.ExcelWriter("media/"+file_path) as writer:
    #     df.to_excel(writer, sheet_name='Planning Situation', index=False)
        
        # for k, v in datas_dict_planning.items():
        #     if k != 'Précédentes':
        #         pd.DataFrame(
        #             v
        #         ).to_excel(writer, sheet_name=k, index=False)

        
    if platform == "win32":
        # windows
        return file_path.replace("/", "\\\\")
    else:
        return file_path