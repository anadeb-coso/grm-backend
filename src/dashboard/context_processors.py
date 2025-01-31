from django.conf import settings


def settings_vars(request):
    return {
        'OTHER_LANGUAGES': settings.OTHER_LANGUAGES,
                
        'DOMAIN_PATH': ("http://" if "127." in request.get_host() else "https://") + (request.get_host()),

        "CDD_URL_BASE": settings.CDD_URL_BASE,
        "MIS_URL_BASE": settings.MIS_URL_BASE,
        "GRM_URL_BASE": settings.GRM_URL_BASE,
    }
