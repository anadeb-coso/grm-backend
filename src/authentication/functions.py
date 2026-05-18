from django.utils.translation import gettext_lazy as _
from grm.my_librairies.mail.send_mail import send_email
from datetime import datetime
import requests
from django.conf import settings


def send_code_by_mail(user, code):
    try:
        return send_email(
            _("Validation code for your GRM account"),
            "mail/send/comment",
            {
                "datas": {
                    _("Title"): _("Validation code for your GRM account"),
                    _("Code"): code,
                    _("Comment"): _("Please do not share this code with anyone until it has been used.")
                },
                "user": {
                    _("Name"): f"{user.first_name} {user.last_name}",
                    _("Phone"): user.phone_number,
                    _("Email"): user.email
                },
                "user_full_name": f"{user.first_name} {user.last_name}",
                "comment":  _("Please find below your account information."), 
                "greeting":  _("Hello"),
                "all_sex":  _("Mr./Mrs."),
                'current_year': datetime.now().year,
                
                # "url": f"{request.scheme}://{request.META['HTTP_HOST']}{reverse_lazy('dashboard:facilitators:detail', args=[no_sql_db_name])}"
            },
            [user.email]
        )
    except:
        return None


def update_user_adl_on_cdd_app(
        facilitator_email, grm_secret_key_generate, stabilization_administrative_ids, additional_administrative_ids
):
    url = f"{settings.CDD_URL_BASE}/authentication/api/facilitators/update-user-adls/"

    data = {
        "facilitator_email": facilitator_email,
        "grm_secret_key_generate": grm_secret_key_generate,
        "stabilization_administrative_ids": stabilization_administrative_ids,
        "additional_administrative_ids": additional_administrative_ids
    }
    # try:
    response = requests.post(url, json=data)
    # except:
    #     pass