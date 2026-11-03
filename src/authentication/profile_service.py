"""Profile page of the logged-in user, the same as the DCC one but served by the MGP itself.

The MGP account (this database) is read here; what the DCC knows about the person (DCC web / SIG account,
facilitator account, roles, projects, area of intervention) is asked to the DCC
(`authentication/api/person-profile/`). The password change is done by the DCC for all the person's accounts
(`authentication/api/change-password/`), which pushes the new password back to this MGP account
(`api/service/users/set-password/`). Both calls use the shared secret `GRM_SECRET_KEY_GENRATE`."""
import logging

import requests
from django.conf import settings
from django.utils.translation import gettext as _, gettext_lazy

logger = logging.getLogger(__name__)

FEMALE_VALUES = {'mme', 'mlle', 'f', 'femme', 'female', 'féminin', 'feminin'}
MALE_VALUES = {'m.', 'm', 'mr', 'h', 'homme', 'male', 'masculin'}
FACILITATOR_TYPES = {'community_facilitator': gettext_lazy("Community facilitator"),
                     'technical_facilitator': gettext_lazy("Technical facilitator")}


def gender_of(sex):
    value = (sex or '').strip().lower()
    if value in FEMALE_VALUES:
        return 'female'
    if value in MALE_VALUES:
        return 'male'
    return None


def person_profile_from_cdd(email, language=None):
    """DCC part of the profile, or None if the DCC cannot be reached."""
    if not email:
        return None
    try:
        response = requests.post(
            f"{settings.CDD_URL_BASE}/authentication/api/person-profile/",
            json={'secret': settings.GRM_SECRET_KEY_GENRATE, 'email': email, 'language': language}, timeout=20,
        )
        return response.json() if response.status_code == 200 else None
    except (requests.RequestException, ValueError) as exc:
        logger.warning("DCC profile not read: %s", exc)
        return None


def change_password_on_all_platforms(email, current_password, new_password, confirmation, language=None):
    """New password for all the person's accounts (DCC, SIG, facilitator, MGP), done by the DCC. (ok, message)."""
    try:
        response = requests.post(
            f"{settings.CDD_URL_BASE}/authentication/api/change-password/",
            json={
                'secret': settings.GRM_SECRET_KEY_GENRATE, 'login': email, 'current_password': current_password,
                'new_password': new_password, 'new_password_confirm': confirmation, 'platform': 'mgp_web',
                'language': language,
            },
            # the DCC pushes the password back to this MGP account before answering
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


def build_profile_details(user, language=None):
    cdd = person_profile_from_cdd(user.email, language)
    facilitator = (cdd or {}).get('facilitator')
    gender = gender_of((facilitator or {}).get('sex'))
    usernames = []
    for name in (user.username, (facilitator or {}).get('username')):
        if name and name not in usernames:
            usernames.append(name)
    groups = set(user.groups.values_list('name', flat=True)) | set((cdd or {}).get('groups') or [])
    return {
        'user': user,
        'cdd_reachable': cdd is not None,
        'facilitator': facilitator,
        'facilitator_type': (facilitator or {}).get('type') or None,
        'gender': gender,
        'civility': (facilitator or {}).get('sex'),
        'full_name': user.get_full_name() or user.username,
        'phone': user.phone_number or (facilitator or {}).get('phone'),
        'usernames': usernames,
        'groups': sorted(groups),
        'projects': (cdd or {}).get('projects') or [],
        'zone': (cdd or {}).get('zone'),
        'platforms': [
            {'name': _('Web DCC'), 'icon': 'fa-desktop', 'active': bool((cdd or {}).get('dcc_web')), 'unknown': cdd is None},
            {'name': _('Mobile DCC'), 'icon': 'fa-mobile-alt', 'active': bool((cdd or {}).get('dcc_mobile')), 'unknown': cdd is None},
            {'name': _('SIG (COSOMIS)'), 'icon': 'fa-map-marked-alt', 'active': bool((cdd or {}).get('sig')), 'unknown': cdd is None},
            {'name': _('MGP (GRM)'), 'icon': 'fa-comments', 'active': True},
        ],
    }
