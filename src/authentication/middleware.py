"""Middleware de suivi de la dernière activité des utilisateurs (web + mobile).

Met à jour ``User.last_activity`` au plus une fois toutes les 10 minutes par utilisateur, à
la fin du traitement de chaque requête authentifiée. Couvre :

* le dashboard web (session Django, ``request.user``) ;
* le mobile / les autres services (JWT ``Authorization: Bearer ...``, sans session) — la
  résolution JWT est refaite ici car ``request.user`` reste anonyme au niveau middleware
  pour ces requêtes (l'authentification DRF n'a lieu que dans la vue).

L'écriture se fait via ``QuerySet.update()`` (pas ``save()``) pour ne déclencher ni la
logique ``User.save`` ni les signaux ``post_save`` branchés sur ``User``.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

UPDATE_INTERVAL = timedelta(minutes=10)


class LastActivityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        try:
            self._touch_last_activity(request)
        except Exception:
            # Le suivi d'activité ne doit jamais casser une réponse.
            pass
        return response

    def _touch_last_activity(self, request):
        user = getattr(request, 'user', None)
        if user is None or not user.is_authenticated:
            user = self._user_from_jwt(request)
        if user is None or not getattr(user, 'is_authenticated', False):
            return

        now = timezone.now()
        last_activity = getattr(user, 'last_activity', None)
        if last_activity is None or now - last_activity > UPDATE_INTERVAL:
            # ``request.user`` est un ``SimpleLazyObject`` (session) : passer par le vrai modèle.
            get_user_model().objects.filter(pk=user.pk).update(last_activity=now)

    @staticmethod
    def _user_from_jwt(request):
        """Retourne l'utilisateur porté par un jeton JWT valide, ou ``None``."""
        try:
            from rest_framework_simplejwt.authentication import JWTAuthentication
        except Exception:
            return None
        try:
            result = JWTAuthentication().authenticate(request)
        except Exception:
            return None
        return result[0] if result else None


class PasswordChangeRequiredMiddleware:
    """Compte créé dans le DCC dont le mot de passe initial n'a été changé sur aucune plateforme : toute page du
    dashboard renvoie vers le changement obligatoire (`dashboard:authentication:first_login_password`). Seul le
    namespace `dashboard` est concerné : l'API mobile refuse elle-même le jeton (authentication/serializers.py).
    Vérifié une fois par session. Doit suivre AuthenticationMiddleware."""

    EXEMPT_VIEW_NAMES = {
        'dashboard:authentication:first_login_password',
        'dashboard:authentication:login',
        'dashboard:authentication:logout',
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        from authentication.password_change import CHECKED_SESSION_KEY, password_change_required

        user = getattr(request, 'user', None)
        if user is None or not user.is_authenticated or request.session.get(CHECKED_SESSION_KEY):
            return None
        match = request.resolver_match
        if match is None or tuple(match.namespaces[:1]) != ('dashboard',) or match.view_name in self.EXEMPT_VIEW_NAMES:
            return None
        if not password_change_required(user.email):
            request.session[CHECKED_SESSION_KEY] = True
            return None

        from django.http import JsonResponse
        from django.shortcuts import redirect
        from django.utils.translation import gettext

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'detail': gettext('You must change your password before your first login.'),
                                 'code': 'password_change_required'}, status=403)
        return redirect('dashboard:authentication:first_login_password')
