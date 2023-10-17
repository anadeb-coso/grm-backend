from django.utils.translation import gettext_lazy as _
from grm.my_librairies.mail.send_mail import send_email


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
                # "url": f"{request.scheme}://{request.META['HTTP_HOST']}{reverse_lazy('dashboard:facilitators:detail', args=[no_sql_db_name])}"
            },
            [user.email]
        )
    except:
        return None
