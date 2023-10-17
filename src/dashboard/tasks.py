from django.conf import settings
from django.utils.translation import gettext as _
from twilio.base.exceptions import TwilioRestException
from datetime import datetime

from authentication.models import anonymize_issue_data, get_assignee, get_assignee_to_escalate
from client import get_db
from dashboard.grm import CHOICE_CONTACT, CHOICE_PHONE
from grm.celery import app
from grm.utils import get_auto_increment_id
from sms_client import send_sms
from administrativelevels.functions import get_ald_parent_by_type_and_child_id
from dashboard.grm.functions import send_notification_by_mail, send_notification_on_escalation_by_mail

COUCHDB_GRM_DATABASE = settings.COUCHDB_GRM_DATABASE
COUCHDB_DATABASE_ADMINISTRATIVE_LEVEL = settings.COUCHDB_DATABASE_ADMINISTRATIVE_LEVEL


@app.task
def check_issues():
    """
    Check the issues without 'auto_increment_id', 'internal_code' or 'assignee', and try to set a value for these fields
    """
    grm_db = get_db(COUCHDB_GRM_DATABASE)
    selector = {
        "type": "issue",
        "confirmed": True,
        "$or": [
            {
                "auto_increment_id": {
                    "$in": [
                        None,
                        ""
                    ]
                }
            },
            {
                "auto_increment_id": {
                    "$exists": False
                }
            },
            {
                "internal_code": {
                    "$in": [
                        None,
                        ""
                    ]
                }
            },
            {
                "internal_code": {
                    "$exists": False
                }
            },
            {
                "citizen": {
                    "$nin": [
                        None,
                        "",
                        "*"
                    ]
                }
            },
            {
                "contact_information.contact": {
                    "$nin": [
                        None,
                        "",
                        "*"
                    ]
                }
            },
            {
                "assignee": {
                    "$in": [
                        None,
                        ""
                    ]
                }
            },
            {
                "assignee": {
                    "$exists": False
                }
            }
        ]
    }

    issues = grm_db.get_query_result(selector)
    result = {
        'errors': [],
        'auto_increment_id_updated': [],
        'internal_code_updated': [],
        'anonymized_data': [],
        'assignee_updated': [],
    }
    updated_issues = 0
    for issue in issues:
        auto_increment_id_updated = False
        internal_code_updated = False
        anonymized_data = False
        assignee_updated = False

        issue_id = issue['_id']
        try:
            issue_doc = grm_db[issue_id]
        except Exception:
            error = f'Error trying to get issue document with id {issue_id}'
            result['errors'].append(error)
            return result

        if 'auto_increment_id' not in issue_doc or not issue_doc['auto_increment_id']:
            try:
                auto_increment_id = get_auto_increment_id(grm_db)
                issue_doc['auto_increment_id'] = auto_increment_id
                auto_increment_id_updated = True
                result['auto_increment_id_updated'].append(issue_id)
            except Exception:
                error = f'Error trying to set auto_increment_id of issue document with id {issue_id}'
                result['errors'].append(error)
        else:
            auto_increment_id = issue_doc['auto_increment_id']

        try:
            category_id = issue_doc['category']['id']
            doc_category = grm_db.get_query_result({
                "id": category_id,
                "type": 'issue_category'
            })[0][0]
        except Exception:
            error = f'Error trying to get the category of issue document with id {issue_id}'
            result['errors'].append(error)
            continue

        if 'internal_code' not in issue_doc or not issue_doc['internal_code']:
            try:
                administrative_id = issue_doc["administrative_region"]["administrative_id"]
                issue_doc['internal_code'] = f'{doc_category["abbreviation"]}-{administrative_id}-{auto_increment_id}'
                internal_code_updated = True
                result['internal_code_updated'].append(issue_id)
            except Exception:
                error = f'Error trying to set internal_code for issue document with id {issue_id}'
                result['errors'].append(error)

        contact_information = issue_doc['contact_information']
        if issue_doc['citizen'] != '*' or (contact_information and contact_information['contact'] != '*'):
            try:
                anonymize_issue_data(issue_doc)
                anonymized_data = True
                result['anonymized_data'].append(issue_id)
            except Exception:
                error = f'Error trying to anonymize issue document with id {issue_id}'
                result['errors'].append(error)

        if 'assignee' not in issue_doc or not issue_doc['assignee']:
            try:
                eadl_db = get_db()
                adl_db = get_db(COUCHDB_DATABASE_ADMINISTRATIVE_LEVEL)
                assignee = get_assignee(grm_db, eadl_db, adl_db, issue_doc, result['errors'])
                issue_doc['assignee'] = assignee
                if assignee:
                    assignee_updated = True
                    result['assignee_updated'].append(issue_id)
            except Exception:
                error = f'Error trying to set assignee for issue document with id {issue_id}'
                result['errors'].append(error)

        if auto_increment_id_updated or internal_code_updated or anonymized_data or assignee_updated:
            issue_doc.save()
            updated_issues += 1
            grm_db = get_db(COUCHDB_GRM_DATABASE)  # refresh db

    result['updated_issues'] = updated_issues
    return result


@app.task
def escalate_issues():
    grm_db = get_db(COUCHDB_GRM_DATABASE)
    selector = {
        "type": "issue",
        "confirmed": True,
        "escalate_flag": True,
        "assignee": {"$ne": ""}
    }

    issues = grm_db.get_query_result(selector)
    result = {
        'errors': [],
        'issues_updated': [],
        'scale_is_not_available': [],
    }
    updated_issues = 0
    for issue in issues:
        issues_updated = False
        issue_id = issue['_id']
        try:
            issue_doc = grm_db[issue_id]
        except Exception:
            error = f'Error trying to get issue document with id {issue_id}'
            result['errors'].append(error)
            continue
        try:
            category_id = issue_doc['category']['id']
            doc_category = grm_db.get_query_result({
                "id": category_id,
                "type": 'issue_category'
            })[0][0]
            department_id = doc_category['assigned_department']['id']
            administrative_id = issue_doc['administrative_region']['administrative_id']

            #Building the escate list
            escalation_administrativelevels = issue_doc['escalation_administrativelevels'] if 'escalation_administrativelevels' in issue_doc else list()
            
            for i_escalation in range(len(escalation_administrativelevels)):
                if not escalation_administrativelevels[i_escalation].get('comment'):
                    # try:
                    ald_to_escalation = get_ald_parent_by_type_and_child_id(
                        escalation_administrativelevels[i_escalation]['escalate_to']['administrative_level'],
                        administrative_id
                    )
                    escalate_to_administrative = {
                        "administrative_id": str(ald_to_escalation.id),
                        "name": ald_to_escalation.name,
                        "administrative_level": ald_to_escalation.type
                    }
                    # except:
                    #     ald_to_escalation = None
                    if ald_to_escalation:
                        escalation_administrativelevels[i_escalation] = {
                            "escalate_to": escalate_to_administrative,
                            "comment": (escalation_administrativelevels[i_escalation-1]['escalate_to']['name'] if \
                                        (i_escalation > 0) and len(escalation_administrativelevels) > 1 else issue_doc['administrative_region']['name']) \
                                            + " " + _("to") + " " + escalate_to_administrative['name'] + \
                                                " (" + escalate_to_administrative['administrative_level'] + ")",
                            "due_at": escalation_administrativelevels[i_escalation]["due_at"]
                        }

            #Search the last escalate
            if escalation_administrativelevels:
                administrative_id = escalation_administrativelevels[0]['escalate_to']['administrative_id']
                
            adl_db = get_db(COUCHDB_DATABASE_ADMINISTRATIVE_LEVEL)
            assignee, escalate_to_administrative = get_assignee_to_escalate(adl_db, department_id, administrative_id)
            
            if assignee:
                # issue_doc['assignee'] = assignee
                issue_doc['escalate_flag'] = False
                escalation_administrativelevels.insert(0, {
                    "escalate_to": escalate_to_administrative,
                    "comment": (escalation_administrativelevels[0]['escalate_to']['name'] if \
                                escalation_administrativelevels else issue_doc['administrative_region']['name']) \
                                    + " " + _("to") + " " + escalate_to_administrative['name'] + \
                                        " (" + escalate_to_administrative['administrative_level'] + ")",
                    "due_at": datetime.now().strftime('%Y-%m-%dT%H:%M:%S.%fZ')
                })
                issue_doc['escalation_administrativelevels'] = escalation_administrativelevels

                result['issues_updated'].append(issue_id)
                issues_updated = True

                send_notification_on_escalation_by_mail(issue_doc) #Send mail

            else:
                result['scale_is_not_available'].append(issue_id)

        except Exception:
            error = f'Error trying to escalate for issue document with id {issue_id}'
            result['errors'].append(error)
        if issues_updated:
            try:
                doc_status = grm_db.get_query_result({
                    "open_status": True,
                    "type": 'issue_status'
                })[0][0]
                issue_doc['status'] = {
                    "name": doc_status['name'],
                    "id": doc_status['id']
                }
            except Exception:
                pass
            
            issue_doc.save()
            updated_issues += 1
            grm_db = get_db(COUCHDB_GRM_DATABASE)  # refresh db

    result['updated_issues'] = updated_issues
    return result


@app.task
def send_sms_message():
    messages = {
        'accepted_alert_message': _(
            "Your issue submitted has been accepted into the system with the code %s(tracking_code)s"),
        'rejected_alert_message': _(
            "Your issue %s(tracking_code)s has been rejected with the following response: %s(reason)s"),
        'closed_alert_message': _(
            "Your issue %s(tracking_code)s has been resolved with the following response: %s(resolution)s"),
    }
    grm_db = get_db(COUCHDB_GRM_DATABASE)
    selector = {
        "type": "issue",
        "confirmed": True,
        "assignee": {"$ne": ""},
        "tracking_code": {"$ne": ""},
        "contact_medium": CHOICE_CONTACT,
        "contact_information.type": CHOICE_PHONE,
        "contact_information.contact": {"$ne": ""},
        "$or": [
            {
                "accepted_alert_message": False,
            },
            {
                "accepted_alert_message": {
                    "$exists": False
                }
            },
            {
                "rejected_alert_message": False,
            },
            {
                "rejected_alert_message": {
                    "$exists": False
                }
            },
            {
                "closed_alert_message": False,
            },
            {
                "closed_alert_message": {
                    "$exists": False
                }
            },
        ]
    }

    issues = grm_db.get_query_result(selector)
    result = {
        'errors': [],
        'notified_issues': [],
    }
    updated_issues = 0
    for issue in issues:
        notified_issues = False
        issue_id = issue['_id']
        try:
            issue_doc = grm_db[issue_id]
        except Exception:
            error = f'Error trying to get issue document with id {issue_id}'
            result['errors'].append(error)
            continue
        try:
            status_id = issue_doc['status']['id']
            doc_status = grm_db.get_query_result({
                "id": status_id,
                "type": 'issue_status'
            })[0][0]
        except Exception:
            error = f'Error trying to get issue_status document with id {status_id}'
            result['errors'].append(error)
            continue

        tracking_code = issue_doc['tracking_code']
        phone = issue_doc['contact_information']['contact']

        no_alert = 'accepted_alert_message' not in issue_doc or not issue_doc['accepted_alert_message']
        if no_alert and doc_status['open_status']:
            msg = messages['accepted_alert_message'] % {'tracking_code': tracking_code}
            try:
                send_sms(phone, msg)
                notified_issues = True
                issue_doc['accepted_alert_message'] = True
            except TwilioRestException as e:
                result['errors'].append(e.msg)

        no_alert = 'rejected_alert_message' not in issue_doc or not issue_doc['rejected_alert_message']
        if no_alert and doc_status['rejected_status']:
            msg = messages['rejected_alert_message'] % {
                'tracking_code': tracking_code,
                'reason': issue_doc['rejected_alert_message'] if 'rejected_alert_message' in issue_doc else ''
            }
            try:
                send_sms(phone, msg)
                notified_issues = True
                issue_doc['rejected_alert_message'] = True
            except TwilioRestException as e:
                result['errors'].append(e.msg)

        no_alert = 'closed_alert_message' not in issue_doc or not issue_doc['closed_alert_message']
        if no_alert and doc_status['final_status']:
            msg = messages['closed_alert_message'] % {
                'tracking_code': tracking_code,
                'resolution': issue_doc['research_result'] if 'research_result' in issue_doc else ''
            }
            try:
                send_sms(phone, msg)
                notified_issues = True
                issue_doc['closed_alert_message'] = True
            except TwilioRestException as e:
                result['errors'].append(e.msg)

        if notified_issues:
            issue_doc.save()
            updated_issues += 1
            grm_db = get_db(COUCHDB_GRM_DATABASE)  # refresh db

    result['updated_issues'] = updated_issues
    return result



@app.task
def send_a_new_issue_notification():
    """
    Check the issues without 'auto_increment_id', 'internal_code' or 'assignee', and try to set a value for these fields
    """
    grm_db = get_db(COUCHDB_GRM_DATABASE)
    selector = {
        "type": "issue",
        "confirmed": True,
        "$or": [
            {
                "notification_send": False,
            },
            {
                "notification_send": {
                    "$exists": False
                }
            }
        ]
    }

    issues = grm_db.get_query_result(selector)
    
    for issue in issues:
        try:
            issue_doc = grm_db[issue['_id']]
            send_notification_by_mail(issue)
            issue_doc['notification_send'] = True
            issue_doc.save()
        except Exception:
            continue
            




@app.on_after_finalize.connect
def setup_periodic_tasks(sender, **kwargs):
    # Calls check_issues() every 5 minutes.
    sender.add_periodic_task(300, check_issues.s(), name='check issues every 5 minutes')

    # Calls escalate_issues() every 5 minutes.
    sender.add_periodic_task(300, escalate_issues.s(), name='escalate issues every 5 minutes')

    # Calls send_sms_message() every 5 minutes.
    sender.add_periodic_task(300, send_sms_message.s(), name='send sms every 5 minutes')
    
    # Calls send_a_new_issue_notification() every 5 minutes.
    sender.add_periodic_task(300, send_a_new_issue_notification.s(), name='send sms every 5 minutes')
