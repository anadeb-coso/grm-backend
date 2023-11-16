from django.utils.translation import gettext_lazy as _
from datetime import datetime

from grm.utils import datetime_str
from grm.my_librairies.mail.send_mail import send_email
from grm.constants import (
    SAFEGUARD_SPECIALIST_EMAILS, OTHER_SPECIALIST_ON_MAIL_COPY, ANADEB_EMAILS_ON_COPY,
    OTHERS_EMAILS_ON_COPY, ASSISTANTS_SAFEGUARD_SPECIALIST_EMAILS, COORDINATORS_EMAILS_ON_COPY
)
from administrativelevels.models import AdministrativeLevel
from grm.my_librairies.functions import strip_accents
from grm.call_objects_from_other_db import mis_objects_call


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