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
        facilitator_email, grm_secret_key_generate, stabilization_administrative_ids, additional_administrative_ids,
        administrative_id=None, administrative_ids=None, additional_administrative_region_ids=None, notify=True,
):
    """Transmet à CDD les villages (et, pour que CDD garde exactement le choix de l'agent, le niveau
    principal et les niveaux choisis avant calcul des villages) d'un EADL. `notify=False` : CDD
    n'envoie pas d'email au facilitateur (remplissage initial, cf. commande `push_adls_to_cdd`)."""
    url = f"{settings.CDD_URL_BASE}/authentication/api/facilitators/update-user-adls/"

    data = {
        "facilitator_email": facilitator_email,
        "grm_secret_key_generate": grm_secret_key_generate,
        "stabilization_administrative_ids": stabilization_administrative_ids,
        "additional_administrative_ids": additional_administrative_ids,
        "administrative_id": administrative_id,
        "administrative_ids": administrative_ids,
        "additional_administrative_region_ids": additional_administrative_region_ids,
        "notify": notify,
    }
    # try:
    # `timeout` : CDD peut lui-même être en train d'attendre la réponse du GRM (modification des
    # localités depuis CDD -> GRM -> renvoi ici) ; ne jamais bloquer indéfiniment.
    response = requests.post(url, json=data, timeout=60)
    return response
    # except:
    #     pass