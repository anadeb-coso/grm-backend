from django.conf import settings
from rest_framework.permissions import BasePermission

SERVICE_KEY_HEADER = 'HTTP_X_GRM_SECRET'


class HasGrmServiceKey(BasePermission):
    """Autorise un appel machine-à-machine (CDD, MIS) porteur du secret partagé
    `GRM_SECRET_KEY_GENRATE` — même secret déjà utilisé par l'intégration existante
    GRM -> CDD (authentication/functions.py::update_user_adl_on_cdd_app,
    authentication/api/auth/login.py::CheckUserSerializer). Ces endpoints ne représentent
    aucun utilisateur final : pas de JWT, un service de confiance appelle pour le compte
    d'une autre plateforme (Section B du CLAUDE.md)."""

    message = 'Invalid or missing service key.'

    def has_permission(self, request, view):
        provided = request.META.get(SERVICE_KEY_HEADER) or request.GET.get('grm_secret_key_generate') \
            or (request.data.get('grm_secret_key_generate') if hasattr(request, 'data') else None)
        return bool(provided) and provided == settings.GRM_SECRET_KEY_GENRATE
