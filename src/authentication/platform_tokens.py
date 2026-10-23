"""Jetons de session du mobile DCC, délivrés par le DCC à la connexion et valables sur le DCC, le SIG et le MGP
(cdd-backend : authentication/platform_tokens.py). Le mobile DCC les envoie au MGP dans l'en-tête
`Authorization: Bearer <jeton>` (préfixe `cps_`, ce qui les distingue des JWT du MGP).

Le MGP les vérifie en lisant la table du DCC `authentication_platformaccesstoken` (base partagée, connexion `mis`),
avec les mêmes règles que le DCC : empreinte SHA-256 du jeton connue, ni expiré ni révoqué, compte DCC actif, mot de
passe inchangé depuis la délivrance. Le compte MGP est celui de même e-mail (même personne). Lecture seule."""
import hashlib
import logging

from django.contrib.auth import get_user_model
from django.db import connections, transaction
from django.utils.translation import gettext_lazy as _
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication, get_authorization_header

logger = logging.getLogger(__name__)

PREFIX = 'cps_'
TABLE = 'authentication_platformaccesstoken'
ACCOUNT_QUERIES = {
    'facilitator': "SELECT email, active, password FROM authentication_facilitator WHERE id = %s",
    'user': "SELECT email, is_active, password FROM auth_user WHERE id = %s",
}


def is_platform_token(value):
    return isinstance(value, str) and value.startswith(PREFIX)


def password_fingerprint(password_hash):
    return hashlib.sha256((password_hash or '').encode('utf-8')).hexdigest()


def email_from_token(token):
    """E-mail (en minuscules) du compte DCC désigné par un jeton valide, sinon None. Base partagée injoignable ou
    table absente (DCC pas encore migré) : None."""
    if not is_platform_token(token) or 'mis' not in connections:
        return None
    key_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
    try:
        # point de sauvegarde : une erreur (table absente) ne doit pas rendre inutilisable une transaction en cours
        with transaction.atomic(using='mis'), connections['mis'].cursor() as cursor:
            cursor.execute(
                "SELECT account_kind, account_id, password_fingerprint FROM {} "
                "WHERE key_hash = %s AND revoked_at IS NULL AND expires_at > now()".format(TABLE),
                [key_hash],
            )
            row = cursor.fetchone()
            if row is None or row[0] not in ACCOUNT_QUERIES:
                return None
            kind, account_id, fingerprint = row
            cursor.execute(ACCOUNT_QUERIES[kind], [account_id])
            account = cursor.fetchone()
    except Exception as exc:
        logger.warning("Platform token not read: %s", exc)
        return None
    if account is None:
        return None
    email, active, password_hash = account
    if not active or password_fingerprint(password_hash) != fingerprint:
        return None
    email = (email or '').strip().lower()
    return email or None


def user_from_token(token):
    """Compte MGP actif de la même personne (même e-mail) que le compte DCC du jeton, sinon None."""
    email = email_from_token(token)
    if not email:
        return None
    return get_user_model().objects.filter(email__iexact=email, is_active=True).order_by('id').first()


class PlatformTokenAuthentication(BaseAuthentication):
    """`Authorization: Bearer cps_...` (jeton du mobile DCC). Les autres en-têtes Bearer (JWT du MGP) sont laissés à
    JWTAuthentication. Jeton refusé : 401 avec `token_invalid` (le mobile ferme la session)."""

    def authenticate(self, request):
        parts = get_authorization_header(request).split()
        if len(parts) != 2 or parts[0].lower() != b'bearer':
            return None
        try:
            token = parts[1].decode('utf-8')
        except UnicodeError:
            return None
        if not is_platform_token(token):
            return None
        email = email_from_token(token)
        if not email:
            raise exceptions.AuthenticationFailed({
                'detail': _("Your session has expired. Please log in again."),
                'token_invalid': True,
            })
        user = get_user_model().objects.filter(email__iexact=email, is_active=True).order_by('id').first()
        if user is None:
            # Jeton valable (session DCC ouverte), mais la personne n'a pas de compte actif sur le MGP : ce n'est pas
            # une session expirée — le mobile ne doit pas redemander le mot de passe (cas des comptes de formation).
            raise exceptions.PermissionDenied({
                'detail': _("This account has no access to the MGP."),
                'no_grm_account': True,
            })
        return user, None

    def authenticate_header(self, request):
        return 'Bearer realm="api"'
