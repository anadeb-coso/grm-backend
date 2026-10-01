from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class InternetCreditsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'internet_credits'
    verbose_name = _('CVGP internet credits')
