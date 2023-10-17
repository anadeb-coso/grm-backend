from django.utils.translation import gettext_lazy as _
from datetime import datetime

from grm.utils import datetime_str
from grm.my_librairies.mail.send_mail import send_email
from grm.constants import SAFEGUARD_SPECIALIST_EMAILS, OTHER_SPECIALIST_ON_MAIL_COPY, ANADEB_EMAILS_ON_COPY


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
            cc= OTHER_SPECIALIST_ON_MAIL_COPY + ANADEB_EMAILS_ON_COPY
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
            cc= OTHER_SPECIALIST_ON_MAIL_COPY + ANADEB_EMAILS_ON_COPY
        )
    except:
        return None