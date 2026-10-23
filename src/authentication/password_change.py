"""Mot de passe initial à changer à la première connexion, pour les comptes créés dans le DCC (utilisateurs et
facilitateurs, ces derniers étant aussi créés ici par `api/service/users/facilitator/`).

L'obligation est rangée par le DCC dans sa table `authentication_passwordchangerequirement` (base partagée,
lue ici par la connexion `mis`, en minuscules dans `email`) ; le DCC la lève dès que la personne change son mot de
passe sur n'importe quelle plateforme (DCC, MGP, SIG). Le changement lui-même passe par le DCC
(`authentication/api/first-login-password/`), qui reporte le nouveau mot de passe sur le compte MGP
(`api/service/users/set-password/`) : un seul mot de passe pour toutes les plateformes."""
import logging

import requests
from django.conf import settings
from django.db import connections, transaction
from django.utils.translation import gettext as _

logger = logging.getLogger(__name__)

REQUIREMENTS_TABLE = 'authentication_passwordchangerequirement'
# Posé dans la session web une fois vérifié qu'aucun changement n'est en attente.
CHECKED_SESSION_KEY = 'password_change_checked'


def password_change_required(email):
    """True si un changement imposé est en attente pour cet e-mail. Base partagée injoignable ou table absente
    (DCC pas encore migré) : False, la connexion n'est jamais bloquée pour autant."""
    email = (email or '').strip()
    if not email or 'mis' not in connections:
        return False
    try:
        # point de sauvegarde : une erreur (table absente) ne doit pas rendre inutilisable une transaction en cours
        with transaction.atomic(using='mis'), connections['mis'].cursor() as cursor:
            cursor.execute(
                f"SELECT 1 FROM {REQUIREMENTS_TABLE} WHERE changed_at IS NULL AND email = lower(%s) LIMIT 1",
                [email],
            )
            return cursor.fetchone() is not None
    except Exception as exc:
        logger.warning("Password change requirement not read: %s", exc)
        return False


def remember_password_change_check(sender, request, user, **kwargs):
    """Connexion web (`user_logged_in`) : vérification faite une fois et rangée dans la session, les pages suivantes
    n'interrogent plus la base (PasswordChangeRequiredMiddleware). En attente : rien n'est rangé, le middleware
    renvoie vers le changement."""
    session = getattr(request, 'session', None)
    if session is not None and not password_change_required(getattr(user, 'email', None)):
        session[CHECKED_SESSION_KEY] = True


def change_initial_password_on_cdd(email, current_password, new_password, confirmation, platform, language=None):
    """Changement imposé fait par le DCC pour toutes les plateformes. Renvoie (ok, message)."""
    try:
        response = requests.post(
            f"{settings.CDD_URL_BASE}/authentication/api/first-login-password/",
            json={
                'login': email, 'current_password': current_password, 'new_password': new_password,
                'new_password_confirm': confirmation, 'platform': platform, 'language': language,
            },
            # le DCC reporte le mot de passe sur le MGP (cette application) avant de répondre
            timeout=60,
        )
    except requests.RequestException as exc:
        logger.warning("DCC unreachable for the password change: %s", exc)
        return False, _("The password could not be changed: the DCC platform cannot be reached. Please try again later.")
    try:
        data = response.json()
    except ValueError:
        return False, _("The password could not be changed (error %(status)s).") % {'status': response.status_code}
    return bool(data.get('ok')), data.get('message') or ''
