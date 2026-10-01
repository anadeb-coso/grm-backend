"""Logique métier des confirmations de forfait internet CVGP, partagée par la sync WatermelonDB
(mobile MGP, sync/views.py), l'API REST (mobile DCC, internet_credits/api_views.py) et l'espace
web (dashboard/internet_credits/)."""
import logging
import uuid
from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Prefetch, Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from issue.models import Adl
from .models import (
    CVGP_GROUP, FC_GROUPS, InternetCreditBeneficiary, InternetCreditCampaign,
    InternetCreditConfirmation, render_message,
)

logger = logging.getLogger(__name__)
User = get_user_model()

SIGNATURE_PREFIXES = ('data:image/png;base64,', 'data:image/jpeg;base64,', 'data:image/jpg;base64,')
MAX_SIGNATURE_LENGTH = 600_000  # ~450 Ko d'image : largement au-dessus d'une signature PNG de pad


class ConfirmationRejected(Exception):
    """Confirmation refusée : `code` est stable (utilisé par les clients mobiles), `message`
    lisible par un humain."""

    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


# ---------------------------------------------------------------------------
# Périmètres (villages) et rattachement au CVD
# ---------------------------------------------------------------------------

def adl_village_ids(user, include_additional=True):
    """Ids (chaînes) des villages rattachés à `user` via ses `Adl` non supprimés — même union
    que sync.views._user_administrative_ids pour le périmètre d'un FC/AC."""
    fields = ['administrative_region_ids_value', 'smallest_administrative_level_ids_value']
    if include_additional:
        fields += ['additional_administrative_region_ids_value', 'additional_smallest_administrative_level_ids_value']
    ids = set()
    for adl in Adl.objects.filter(representative=user, is_deleted=False):
        for field in fields:
            ids.update(str(v) for v in (getattr(adl, field) or []))
    return ids


def fetch_cvd_info(village_ids):
    """Interroge `mis` : pour des ids de villages, renvoie `(cvds, village_names)` où `cvds` est la
    liste des CVD trouvés (`{'id', 'name', 'villages': [(id, name), ...]}`) et `village_names` un
    dict id -> nom des villages demandés. Isolé ici pour être remplacé dans les tests (la base
    `mis` n'est jamais ouverte en test, cf. grm/test_settings.py)."""
    from administrativelevels.models import CVD, AdministrativeLevel

    int_ids = [int(v) for v in village_ids if str(v).isdigit()]
    levels = list(AdministrativeLevel.objects.using('mis').filter(id__in=int_ids).values('id', 'name', 'cvd_id'))
    village_names = {str(level['id']): level['name'] for level in levels}
    cvd_ids = sorted({level['cvd_id'] for level in levels if level['cvd_id']})

    cvds = []
    for cvd in CVD.objects.using('mis').filter(id__in=cvd_ids):
        villages = list(
            AdministrativeLevel.objects.using('mis').filter(cvd_id=cvd.id).order_by('name').values_list('id', 'name')
        )
        name = cvd.name or '/'.join(n for _, n in villages) or cvd.unique_code
        cvds.append({'id': cvd.id, 'name': name, 'villages': [(str(i), n) for i, n in villages]})
    return cvds, village_names


def resolve_member_cvd(user):
    """Rattache un membre CVGP à son CVD à partir des villages de ses `Adl`. Un CVGP = un CVD :
    si aucun ou plusieurs CVD sont trouvés, on garde quand même la ligne (le membre reçoit son
    forfait) avec ses villages comme libellé, et on renseigne `warning` pour l'afficher sur le web."""
    village_ids = sorted(adl_village_ids(user, include_additional=False), key=lambda v: (len(v), v))
    result = {'cvd_id': None, 'cvd_name': '', 'village_ids': village_ids, 'village_names': '', 'warning': ''}
    if not village_ids:
        result['warning'] = 'Aucun village rattaché à ce membre CVGP'
        return result

    try:
        cvds, village_names = fetch_cvd_info(village_ids)
    except Exception as exc:  # base `mis` indisponible : on n'empêche pas la génération
        logger.exception('Résolution du CVD impossible pour %s', user)
        result['village_names'] = ', '.join(village_ids)
        result['warning'] = f'Base mis indisponible : {exc}'
        return result

    if len(cvds) == 1:
        cvd = cvds[0]
        result.update({
            'cvd_id': cvd['id'],
            'cvd_name': cvd['name'],
            'village_ids': [i for i, _ in cvd['villages']] or village_ids,
            'village_names': ', '.join(n for _, n in cvd['villages']),
        })
        return result

    result['village_names'] = ', '.join(village_names.get(v, v) for v in village_ids)
    result['cvd_name'] = result['village_names']
    result['warning'] = 'Aucun CVD trouvé' if not cvds else f'{len(cvds)} CVD trouvés ({", ".join(c["name"] for c in cvds)})'
    return result


def _member_display_name(user):
    return (user.name or '').strip() or user.email or user.username


def render_beneficiary_messages(campaign, beneficiary):
    context = campaign.message_context(
        cvd=beneficiary.label, villages=beneficiary.village_names,
        nom=beneficiary.member_name, telephone=beneficiary.phone_number,
    )
    beneficiary.cvgp_message = render_message(campaign.cvgp_message_template, context)
    beneficiary.fc_message = render_message(campaign.fc_message_template, context)


def sync_campaign_beneficiaries(campaign):
    """Crée une ligne par membre CVGP actif, met à jour les lignes non encore confirmées (CVD,
    téléphone, messages) et retire (tombstone) les lignes non confirmées des membres qui ne sont
    plus CVGP actifs. Les lignes déjà confirmées ne sont jamais modifiées. Idempotent."""
    stats = {'created': 0, 'refreshed': 0, 'removed': 0, 'warnings': []}
    members = User.objects.filter(groups__name=CVGP_GROUP, is_active=True).distinct().order_by('id')
    existing = {
        b.cvgp_member_id: b
        for b in campaign.beneficiaries.filter(is_deleted=False).prefetch_related(active_confirmations_prefetch())
    }

    with transaction.atomic():
        for member in members:
            beneficiary = existing.pop(member.id, None)
            if beneficiary is not None and beneficiary.active_confirmations:
                continue  # déjà confirmé (même partiellement) : figé

            info = resolve_member_cvd(member)
            if beneficiary is None:
                beneficiary = InternetCreditBeneficiary(campaign=campaign, cvgp_member=member)
                stats['created'] += 1
            else:
                stats['refreshed'] += 1
            beneficiary.member_name = _member_display_name(member)
            beneficiary.phone_number = member.phone_number or ''
            beneficiary.cvd_id = info['cvd_id']
            beneficiary.cvd_name = info['cvd_name']
            beneficiary.village_ids = info['village_ids']
            beneficiary.village_names = info['village_names']
            beneficiary.resolution_warning = info['warning'][:255]
            render_beneficiary_messages(campaign, beneficiary)
            beneficiary.save()
            if info['warning']:
                stats['warnings'].append(f'{beneficiary.member_name} : {info["warning"]}')

        # Membres qui ne sont plus CVGP actifs : on retire leur ligne seulement si personne n'a
        # encore confirmé (une confirmation existante reste une trace à conserver).
        for beneficiary in existing.values():
            if not beneficiary.active_confirmations:
                beneficiary.is_deleted = True
                beneficiary.save()
                stats['removed'] += 1
    return stats


def refresh_campaign_messages(campaign):
    """Après modification d'une campagne : re-génère les messages des lignes non confirmées."""
    for beneficiary in campaign.beneficiaries.filter(is_deleted=False).prefetch_related(active_confirmations_prefetch()):
        if not beneficiary.active_confirmations:
            render_beneficiary_messages(campaign, beneficiary)
            beneficiary.save(update_fields=['cvgp_message', 'fc_message', 'updated_at'])


def soft_delete_campaign(campaign):
    """Tombstone de la campagne ET de ses lignes/confirmations (`updated_at` forcé, `.update()`
    ne déclenchant pas `auto_now`) : le pull mobile propage ainsi la suppression de chaque
    notification, confirmée ou non."""
    now = timezone.now()
    with transaction.atomic():
        InternetCreditConfirmation.objects.filter(beneficiary__campaign=campaign, is_deleted=False).update(
            is_deleted=True, updated_at=now,
        )
        campaign.beneficiaries.filter(is_deleted=False).update(is_deleted=True, updated_at=now)
        campaign.is_deleted = True
        campaign.save()


def reset_confirmation(confirmation):
    """Réinitialise une confirmation (web) : la notification réapparaît sur le mobile au pull suivant."""
    confirmation.is_deleted = True
    confirmation.save()


# ---------------------------------------------------------------------------
# Statut des lignes
# ---------------------------------------------------------------------------

def active_confirmations_prefetch():
    return Prefetch(
        'confirmations',
        queryset=InternetCreditConfirmation.objects.filter(is_deleted=False).select_related('confirmed_by'),
        to_attr='active_confirmations',
    )


def get_active_confirmations(beneficiary):
    if hasattr(beneficiary, 'active_confirmations'):
        return beneficiary.active_confirmations
    return list(beneficiary.confirmations.filter(is_deleted=False).select_related('confirmed_by'))


def cvgp_confirmation(beneficiary):
    confirmations = [c for c in get_active_confirmations(beneficiary) if c.role == InternetCreditConfirmation.ROLE_CVGP]
    return confirmations[-1] if confirmations else None


def fc_confirmations(beneficiary):
    return [c for c in get_active_confirmations(beneficiary) if c.role == InternetCreditConfirmation.ROLE_FC]


def campaign_lines(campaign):
    """Lignes actives d'une campagne avec leur statut, pour l'espace web et les exports."""
    beneficiaries = (
        campaign.beneficiaries.filter(is_deleted=False)
        .select_related('cvgp_member')
        .prefetch_related(active_confirmations_prefetch())
        .order_by('cvd_name', 'member_name')
    )
    lines = []
    for index, beneficiary in enumerate(beneficiaries, start=1):
        cvgp = cvgp_confirmation(beneficiary)
        fcs = fc_confirmations(beneficiary)
        lines.append({
            'index': index,
            'beneficiary': beneficiary,
            'cvgp': cvgp,
            'fcs': fcs,
            'fc': fcs[0] if fcs else None,
            'complete': bool(cvgp and fcs),
        })
    return lines


def campaign_stats(lines):
    total = len(lines)
    cvgp_confirmed = sum(1 for line in lines if line['cvgp'])
    fc_confirmed = sum(1 for line in lines if line['fcs'])
    complete = sum(1 for line in lines if line['complete'])
    return {
        'total': total,
        'cvgp_confirmed': cvgp_confirmed,
        'cvgp_pending': total - cvgp_confirmed,
        'fc_confirmed': fc_confirmed,
        'fc_pending': total - fc_confirmed,
        'complete': complete,
        'cvgp_percent': round(cvgp_confirmed * 100 / total) if total else 0,
    }


def is_fc(user):
    return user.groups.filter(name__in=FC_GROUPS).exists()


def role_for(user, beneficiary):
    if beneficiary.cvgp_member_id == user.id:
        return InternetCreditConfirmation.ROLE_CVGP
    return InternetCreditConfirmation.ROLE_FC


def is_pending_for(user, beneficiary):
    """Règle d'affichage de la notification :
    - membre CVGP : visible tant qu'il n'a pas confirmé ;
    - FC/AC : visible tant que les deux confirmations (CVGP + au moins un FC) n'existent pas."""
    cvgp_done = cvgp_confirmation(beneficiary) is not None
    if role_for(user, beneficiary) == InternetCreditConfirmation.ROLE_CVGP:
        return not cvgp_done
    return not (cvgp_done and fc_confirmations(beneficiary))


# ---------------------------------------------------------------------------
# Visibilité (pull mobile, API DCC)
# ---------------------------------------------------------------------------

def beneficiary_visibility_q(user, fc_villages=None):
    """Lignes qu'un utilisateur peut voir : la sienne s'il est membre CVGP, et, s'il est FC/AC,
    celles dont au moins un village du CVD est dans son périmètre."""
    q = Q(cvgp_member_id=user.id)
    if fc_villages is None:
        fc_villages = adl_village_ids(user) if is_fc(user) else set()
    for village_id in fc_villages:
        q |= Q(village_ids__contains=[str(village_id)])
    return q


def pull_visibility_filters(user):
    """Filtres `Q()` par table WatermelonDB, appliqués par sync.views.PullView."""
    beneficiary_q = beneficiary_visibility_q(user)
    visible_ids = InternetCreditBeneficiary.objects.filter(beneficiary_q).values('id')
    return {
        'internet_credit_beneficiaries': beneficiary_q,
        'internet_credit_confirmations': Q(beneficiary_id__in=visible_ids),
    }


def can_confirm_as_fc(user, beneficiary):
    if not is_fc(user):
        return False
    return bool(set(beneficiary.village_ids_value) & adl_village_ids(user))


def pending_notifications(user):
    """Notifications en attente pour `user` (API DCC), du mois le plus récent au plus ancien."""
    beneficiaries = (
        InternetCreditBeneficiary.objects
        .filter(beneficiary_visibility_q(user), is_deleted=False, campaign__is_deleted=False)
        .select_related('campaign')
        .prefetch_related(active_confirmations_prefetch())
        .order_by('-campaign__period', 'cvd_name')
    )
    return [b for b in beneficiaries if is_pending_for(user, b)]


# ---------------------------------------------------------------------------
# Création d'une confirmation (API DCC + push WatermelonDB)
# ---------------------------------------------------------------------------

def _parse_confirmed_at(value):
    now = timezone.now()
    parsed = None
    if isinstance(value, (int, float)):
        parsed = datetime.fromtimestamp(value / 1000, tz=timezone.utc)
    elif isinstance(value, str) and value:
        parsed = parse_datetime(value)
        if parsed is not None and timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed, timezone.utc)
    # Heure de l'appareil conservée (confirmation hors-ligne), sauf valeur absente ou aberrante.
    if parsed is None or parsed > now + timedelta(days=1):
        return now
    return parsed


def _as_uuid(value, code, message):
    if value in (None, ''):
        return None
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        raise ConfirmationRejected(code, message)


def validate_signature(signature):
    if not signature or not isinstance(signature, str) or not signature.startswith(SIGNATURE_PREFIXES):
        raise ConfirmationRejected('invalid_signature', 'La signature est obligatoire (image PNG ou JPEG).')
    if len(signature) > MAX_SIGNATURE_LENGTH:
        raise ConfirmationRejected('signature_too_large', 'La signature est trop volumineuse.')


def create_confirmation(user, data, source):
    """Crée la confirmation décrite par `data` (`id` facultatif, `beneficiary`, `role` facultatif,
    `checked`, `signature`, `description`, `message`, `confirmed_at`) pour `user`.

    Retourne `(confirmation, created)`. Idempotent : même `id` déjà connu, ou même
    (ligne, rôle, utilisateur) déjà confirmé, renvoie la confirmation existante sans rien créer.
    Lève `ConfirmationRejected` si la confirmation n'est pas autorisée."""
    confirmation_id = _as_uuid(data.get('id'), 'invalid_id', 'Identifiant de confirmation invalide.')
    if confirmation_id:
        existing = InternetCreditConfirmation.objects.filter(id=confirmation_id).first()
        if existing is not None:
            if existing.confirmed_by_id != user.id:
                raise ConfirmationRejected('forbidden', 'Cette confirmation appartient à un autre utilisateur.', 403)
            return existing, False

    beneficiary_id = _as_uuid(data.get('beneficiary'), 'unknown_beneficiary', 'Notification introuvable.')
    beneficiary = (
        InternetCreditBeneficiary.objects.select_related('campaign').filter(id=beneficiary_id).first()
        if beneficiary_id else None
    )
    if beneficiary is None:
        raise ConfirmationRejected('unknown_beneficiary', 'Notification introuvable.', 404)
    if beneficiary.is_deleted or beneficiary.campaign.is_deleted:
        raise ConfirmationRejected('campaign_deleted', 'Ce forfait a été supprimé.', 410)

    role = data.get('role') or role_for(user, beneficiary)
    if role == InternetCreditConfirmation.ROLE_CVGP:
        if beneficiary.cvgp_member_id != user.id:
            raise ConfirmationRejected('forbidden', "Seul le membre CVGP concerné peut confirmer pour ce CVD.", 403)
    elif role == InternetCreditConfirmation.ROLE_FC:
        if not can_confirm_as_fc(user, beneficiary):
            raise ConfirmationRejected('forbidden', "Ce CVD n'est pas dans votre périmètre de FC/AC.", 403)
    else:
        raise ConfirmationRejected('invalid_role', 'Rôle de confirmation inconnu.')

    duplicate = InternetCreditConfirmation.objects.filter(
        beneficiary=beneficiary, role=role, confirmed_by=user, is_deleted=False,
    ).first()
    if duplicate is not None:
        return duplicate, False

    if data.get('checked') is not True:
        raise ConfirmationRejected('not_checked', 'La case de confirmation doit être cochée.')
    validate_signature(data.get('signature'))

    default_message = beneficiary.cvgp_message if role == InternetCreditConfirmation.ROLE_CVGP else beneficiary.fc_message
    fields = dict(
        beneficiary=beneficiary,
        role=role,
        confirmed_by=user,
        confirmed_by_name=_member_display_name(user),
        message=(data.get('message') or '').strip() or default_message,
        checked=True,
        signature=data['signature'],
        description=(data.get('description') or '').strip() or None,
        confirmed_at=_parse_confirmed_at(data.get('confirmed_at')),
        source=source,
    )
    if confirmation_id:
        fields['id'] = confirmation_id
    return InternetCreditConfirmation.objects.create(**fields), True


def apply_confirmation_push(user, table_changes):
    """Traite la table `internet_credit_confirmations` d'un push WatermelonDB. Les confirmations
    sont créées uniquement via `create_confirmation` (mêmes contrôles que l'API DCC), jamais
    modifiées ni supprimées depuis le mobile. Une confirmation refusée ne fait pas échouer le push
    (qui bloquerait sinon toute la sync de l'appareil à chaque cycle) : son id est renvoyé dans
    `rejected`, et le mobile la retire de sa base locale (grm-frontend/src/database/sync.js).
    Retourne la liste des ids refusés."""
    rejected = []
    records = list(table_changes.get('created', [])) + list(table_changes.get('updated', []))
    for record in records:
        try:
            with transaction.atomic():
                create_confirmation(user, record, InternetCreditConfirmation.SOURCE_GRM_MOBILE)
        except ConfirmationRejected as exc:
            logger.warning('Confirmation de forfait %s refusée pour %s : %s', record.get('id'), user, exc.message)
            if record.get('id'):
                rejected.append(record['id'])
    return rejected
