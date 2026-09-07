"""Menu "Suivi utilisateur" du dashboard web.

Répond à : combien de comptes utilisateurs sont ouverts sur la plateforme (par profil et
par niveau administratif), et combien ont eu une activité (web ou mobile) au cours des 30
et des 90 derniers jours — plus le nombre d'utilisateurs par Groupe Django et le détail par
compte (``date_joined`` / ``last_login`` / ``last_activity``).

La "dernière activité" (``User.last_activity``) est alimentée par
``authentication.middleware.LastActivityMiddleware`` (web + mobile JWT), au plus une fois
toutes les 10 minutes par compte.

Accès réservé au superuser et au groupe ``Admin`` (``AdminPermissionRequiredMixin``).
"""
from datetime import datetime, timedelta

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import Group
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views import generic

from dashboard.mixins import PageMixin
from authentication.permissions import AdminPermissionRequiredMixin
from authentication.models import User, GovernmentWorker
from grm.models_base import safe_json_value
from administrativelevels.models import AdministrativeLevel
from issue.models import Adl


# Ordre de priorité des profils, calqué sur
# ``dashboard.templatetags.custom_tags.get_group_high`` : chaque compte est rangé sous son
# profil "le plus élevé" (un seul par compte), le superuser primant sur tout.
PROFILE_ORDER = (
    ('Admin', _('Administrator')),
    ('Minister', _('Minister')),
    ('Advisor', _('Advisor')),
    ('GeneralManager', _('General Manager')),
    ('NationalCoordinator', _('National Coordinator')),
    ('RegionalCoordinator', _('Regional Coordinator')),
    ('Director', _('Director')),
    ('Evaluator', _('Evaluator')),
    ('Financial', _('Financial ')),
    ('ProcurementSpecialist', _('Procurement Specialist')),
    ('KnowledgeManager', _('Knowledge manager')),
    ('CDDSpecialist', _('CDD Specialist')),
    ('Accountant', _('Accountant')),
    ('Infra', _('Infra')),
    ('YouthProgramSpecialist', _('Youth Program Specialist')),
    ('LocalEconomicDevelopmentSpecialist', _('Local Economic Development Specialist')),
    ('CommunicationSpecialist', _('Communication Specialist')),
    ('CommunityFacilitator', _('Community Facilitator')),
    ('TechnicalFacilitator', _('Technical Facilitator')),
    ('Supervisor', _('Supervisor')),
    ('Validator', _('Validator')),
)

# (clé GET début, clé GET fin, champ modèle) — chaque plage est indépendante et optionnelle.
DATE_FILTERS = (
    ('activity_start', 'activity_end', 'last_activity'),
    ('login_start', 'login_end', 'last_login'),
    ('joined_start', 'joined_end', 'date_joined'),
)


def _new_bucket():
    return {
        'total': 0,
        'active': 0,
        'inactive': 0,
        'active_30': 0,
        'active_90': 0,
        'never': 0,
    }


def _bump(bucket, is_active, is_a30, is_a90, never):
    bucket['total'] += 1
    bucket['active' if is_active else 'inactive'] += 1
    if is_a30:
        bucket['active_30'] += 1
    if is_a90:
        bucket['active_90'] += 1
    if never:
        bucket['never'] += 1


class UserMonitoringView(AdminPermissionRequiredMixin, PageMixin, LoginRequiredMixin, generic.TemplateView):
    template_name = 'user_tracking/dashboard.html'
    title = _('User monitoring')
    active_level1 = 'user_tracking'
    breadcrumb = [
        {
            'url': '',
            'title': title,
        },
    ]

    @staticmethod
    def _parse_date(value, end_of_day=False):
        if not value:
            return None
        parsed = None
        for fmt in ('%Y-%m-%d', '%d/%m/%Y'):
            try:
                parsed = datetime.strptime(value, fmt)
                break
            except ValueError:
                continue
        if parsed is None:
            return None
        if end_of_day:
            parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
        return parsed

    def _resolve_level_label(self, administrative_id, level_info):
        if not administrative_id:
            return _('Not defined').__str__()
        if str(administrative_id) == '1':
            return 'TOGO ({})'.format(_('Country'))
        info = level_info.get(str(administrative_id))
        if not info:
            return '#{}'.format(administrative_id)
        name, level_type = info
        return '{} ({})'.format(name, level_type) if level_type else name

    @staticmethod
    def _profile_label(user, group_names):
        if user.is_superuser:
            return _('Principal Administrator').__str__()
        for key, label in PROFILE_ORDER:
            if key in group_names:
                return label.__str__()
        return _('User').__str__()

    @staticmethod
    def _as_rows(mapping):
        rows = []
        for label, bucket in mapping.items():
            row = dict(bucket)
            row['label'] = label
            rows.append(row)
        rows.sort(key=lambda r: (-r['total'], str(r['label']).lower()))
        return rows

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        request = self.request

        # --- Filtres de dates (3 plages indépendantes) -------------------------------
        raw = {}
        parsed = {}
        for start_key, end_key, field in DATE_FILTERS:
            raw[start_key] = (request.GET.get(start_key) or '').strip()
            raw[end_key] = (request.GET.get(end_key) or '').strip()
            parsed[start_key] = self._parse_date(raw[start_key], end_of_day=False)
            parsed[end_key] = self._parse_date(raw[end_key], end_of_day=True)

        users_qs = User.objects.all()
        for start_key, end_key, field in DATE_FILTERS:
            if parsed[start_key]:
                users_qs = users_qs.filter(**{f'{field}__gte': parsed[start_key]})
            if parsed[end_key]:
                users_qs = users_qs.filter(**{f'{field}__lte': parsed[end_key]})

        users = list(
            users_qs.prefetch_related('groups').only(
                'id', 'email', 'first_name', 'last_name',
                'is_active', 'is_superuser', 'last_login', 'last_activity', 'date_joined',
            )
        )
        user_ids = [u.id for u in users]

        # Fenêtres 30 / 90 jours (sur ``last_activity``) : ancrées sur la fin de la plage
        # d'activité si elle est fournie, sinon sur l'instant présent.
        anchor = parsed['activity_end'] or timezone.now()
        threshold_30 = anchor - timedelta(days=30)
        threshold_90 = anchor - timedelta(days=90)

        def active_within(user, threshold):
            return user.last_activity is not None and threshold <= user.last_activity <= anchor

        # --- Niveau administratif de chaque compte -------------------------------------
        # 1) agents "gouvernementaux" : GovernmentWorker.administrative_id
        # 2) facilitateurs / représentants : 1er id de Adl.administrative_region_ids
        gw_map = {}
        for gw in GovernmentWorker.objects.filter(user_id__in=user_ids).values(
            'user_id', 'administrative_id',
        ):
            if gw['administrative_id']:
                gw_map[gw['user_id']] = str(gw['administrative_id'])

        adl_map = {}
        for adl in Adl.objects.filter(
            representative_id__in=user_ids, is_deleted=False,
        ).values('representative_id', 'administrative_region_ids'):
            uid = adl['representative_id']
            if uid in gw_map or uid in adl_map:
                continue
            region_ids = safe_json_value(adl['administrative_region_ids']) or []
            if region_ids:
                adl_map[uid] = str(region_ids[0])

        administrative_ids = set(gw_map.values()) | set(adl_map.values())
        administrative_ids_int = [int(x) for x in administrative_ids if str(x).isdigit()]
        level_info = {}
        if administrative_ids_int:
            # Base `mis` (MySQL) — cross-DB, cf. CLAUDE.md §2.1 / §4.2.1.
            for lvl in AdministrativeLevel.objects.using('mis').filter(
                id__in=administrative_ids_int,
            ).values('id', 'name', 'type'):
                level_info[str(lvl['id'])] = (lvl['name'], lvl['type'])

        # --- Agrégations + détail par compte ---------------------------------------
        overall = _new_bucket()
        by_profile = {}
        by_level = {}
        by_group = {name: _new_bucket() for name in Group.objects.values_list('name', flat=True)}
        no_group = _new_bucket()
        detail_rows = []

        for user in users:
            group_names = {g.name for g in user.groups.all()}
            is_active = user.is_active
            is_a30 = active_within(user, threshold_30)
            is_a90 = active_within(user, threshold_90)
            never = user.last_activity is None

            _bump(overall, is_active, is_a30, is_a90, never)

            profile_label = self._profile_label(user, group_names)
            _bump(by_profile.setdefault(profile_label, _new_bucket()), is_active, is_a30, is_a90, never)

            administrative_id = gw_map.get(user.id) or adl_map.get(user.id)
            level_label = self._resolve_level_label(administrative_id, level_info)
            _bump(by_level.setdefault(level_label, _new_bucket()), is_active, is_a30, is_a90, never)

            if group_names:
                for name in group_names:
                    _bump(by_group.setdefault(name, _new_bucket()), is_active, is_a30, is_a90, never)
            else:
                _bump(no_group, is_active, is_a30, is_a90, never)

            detail_rows.append({
                'email': user.email,
                'name': ('{} {}'.format(user.first_name or '', user.last_name or '')).strip(),
                'profile': profile_label,
                'level': level_label,
                'groups': ', '.join(sorted(group_names)) if group_names else '',
                'is_active': is_active,
                'date_joined': user.date_joined,
                'last_login': user.last_login,
                'last_activity': user.last_activity,
            })

        epoch = timezone.make_aware(datetime(1970, 1, 1), timezone.get_current_timezone())
        detail_rows.sort(key=lambda r: (r['last_activity'] or epoch), reverse=True)

        by_group_rows = self._as_rows(by_group)
        if no_group['total']:
            no_group_row = dict(no_group)
            no_group_row['label'] = _('No group').__str__()
            by_group_rows.append(no_group_row)

        context['filters'] = raw
        context['has_filter'] = any(raw.values())
        context['anchor_is_end'] = bool(parsed['activity_end'])
        context['anchor_date'] = anchor
        context['overall'] = overall
        context['by_profile'] = self._as_rows(by_profile)
        context['by_level'] = self._as_rows(by_level)
        context['by_group'] = by_group_rows
        context['groups_count'] = len(by_group)
        context['detail_rows'] = detail_rows
        return context
