import re
from datetime import datetime

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.forms import modelformset_factory
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views import generic

from django.db.models import Q

from dashboard.grm.forms import MultipleDiagnosticsSearchForm, SearchIssueForm
from dashboard.grm.functions import get_multiple_values, get_waves, int_values, waves_administrative_ids
from dashboard.mixins import AJAXRequestMixin, JSONResponseMixin, PageMixin
from grm.utils import (
    get_administrative_level_descendants_using_mis, get_ancestor_administrative_id_by_type_using_mis,
)
from grm.call_objects_from_other_db import mis_objects_call
from administrativelevels.models import AdministrativeLevel
from issue.deadlines import compute_deadline_infos, load_delays
from issue.models import EscalationLevel, Issue, ProcessingDelay, Wave


class HomeFormView(PageMixin, LoginRequiredMixin, generic.FormView):
    form_class = SearchIssueForm
    template_name = 'diagnostics/home.html'
    title = _('Diagnostics')
    active_level1 = 'diagnostics'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context['all_total_issues'] = Issue.objects.filter(confirmed=True, is_deleted=False).count()
        context['access_token'] = settings.MAPBOX_ACCESS_TOKEN
        # Filtres à choix multiple ; les champs de `form` (SearchIssueForm) restent dans la page,
        # masqués (date, localité et niveau administratif sont toujours ceux de `form`).
        context['multi_form'] = MultipleDiagnosticsSearchForm()

        return context


ADMINISTRATIVE_LEVEL_TYPES = ('Region', 'Prefecture', 'Commune', 'Canton', 'Village')

# Sexe du plaignant : le web enregistre 'Male'/'Female', le mobile 'male'/'female'.
FEMALE_VALUES = {'female', 'femme', 'f'}
MALE_VALUES = {'male', 'homme', 'm'}
YOUTH_MAX_AGE = 35  # « jeune » = moins de 35 ans (tranches 0 – 16 et 17 – 35)


def is_youth_age_group(age_group):
    """Vrai si la tranche d'âge se termine au plus à 35 ans (ex. '0 – 16', '17 – 35') ; faux pour
    '36 – 50', '65+'... La borne est lue dans le nom pour ne pas dépendre des ids."""
    if not age_group or not age_group.name or '+' in age_group.name:
        return False
    numbers = [int(n) for n in re.findall(r'\d+', age_group.name)]
    return bool(numbers) and max(numbers) <= YOUTH_MAX_AGE


# Instances d'escalade, de la plus basse à la plus haute (ordre d'affichage). Chaîne de remontée :
# Village -> Canton -> Commune -> National ; Préfecture et Région (anciennes règles) ne sont
# affichées que si des plaintes s'y trouvent encore.
ESCALATION_LEVEL_ORDER = ('Canton', 'Commune', 'Prefecture', 'Region', 'Country')
LEGACY_LEVELS = ('Prefecture', 'Region')
ESCALATION_LEVEL_LABELS = {
    'Canton': _('Canton'),
    'Commune': _('Commune'),
    'Prefecture': _('Prefecture'),
    'Region': _('Region'),
    'Country': _('National'),
}


def compute_escalation_stats(issues):
    """Plaintes escaladées vers une instance supérieure : total + répartition selon l'instance la
    PLUS HAUTE atteinte par chaque plainte (cf. EscalationLevel). On ne se fie pas aux dates :
    dans les données migrées de CouchDB, les niveaux d'une même plainte ont la même date.
    Pourcentages rapportés au total des plaintes."""
    total = len(issues)
    rank = {level: index for index, level in enumerate(ESCALATION_LEVEL_ORDER)}
    highest_level = {}
    levels = (
        EscalationLevel.objects
        .filter(issue_id__in=[i.pk for i in issues], is_deleted=False)
        .values_list('issue_id', 'administrative_level')
    )
    for issue_id, level in levels:
        level = (level or '').strip().capitalize()
        current = highest_level.get(issue_id)
        if current is None or rank.get(level, -1) > rank.get(current, -1):
            highest_level[issue_id] = level

    counts = {}
    for level in highest_level.values():
        counts[level] = counts.get(level, 0) + 1

    def percentage(count):
        return round(count * 100 / total) if total else 0

    by_level = []
    other_levels = sorted(k for k in counts if k not in ESCALATION_LEVEL_ORDER)
    for level in list(ESCALATION_LEVEL_ORDER) + other_levels:
        count = counts.get(level, 0)
        if count or (level in ESCALATION_LEVEL_ORDER and level not in LEGACY_LEVELS):
            name = ESCALATION_LEVEL_LABELS.get(level) or level or _('Not specified')
            by_level.append({'name': str(name), 'count': count, 'issues': count, 'percentage': percentage(count)})

    escalated = len(highest_level)
    return {'total': escalated, 'percentage': percentage(escalated), 'by_level': by_level}


def compute_deadline_stats(issues, infos=None):
    """Plaintes résolues et résolues dans les délais, par niveau (niveau le plus haut atteint),
    avec le nombre de plaintes en cours en retard. Cf. issue/deadlines.py pour les règles."""
    delays = load_delays()
    infos = compute_deadline_infos(issues, delays=delays) if infos is None else infos
    labels = dict(ProcessingDelay.LEVEL_CHOICES)
    committees = {d.level: d.committee_name for d in ProcessingDelay.objects.filter(is_deleted=False)}

    def empty_row(level):
        delay = delays.get(level)
        return {
            'level': level, 'name': str(labels.get(level, level)), 'committee': committees.get(level) or '',
            'delay_days': delay.delay_days if delay else None,
            'working_days': delay.working_days if delay else None,
            'issues': 0, 'resolved': 0, 'resolved_in_time': 0, 'resolved_late': 0,
            'resolved_unknown': 0, 'overdue': 0,
        }

    rows = {level: empty_row(level) for level in ProcessingDelay.LEVEL_ORDER}
    for info in infos.values():
        row = rows[info.level]
        row['issues'] += 1
        if info.resolved:
            row['resolved'] += 1
            if info.resolved_in_time is True:
                row['resolved_in_time'] += 1
            elif info.resolved_in_time is False:
                row['resolved_late'] += 1
            else:
                row['resolved_unknown'] += 1  # délai non défini ou date de résolution inconnue
        if info.overdue:
            row['overdue'] += 1

    total = empty_row('total')
    total.update({'name': str(_('Total')), 'delay_days': None, 'working_days': None})
    for row in rows.values():
        for key in ('issues', 'resolved', 'resolved_in_time', 'resolved_late', 'resolved_unknown', 'overdue'):
            total[key] += row[key]

    def with_rate(row):
        measured = row['resolved_in_time'] + row['resolved_late']
        row['in_time_percentage'] = round(row['resolved_in_time'] * 100 / measured) if measured else None
        return row

    shown = [
        level for level in ProcessingDelay.LEVEL_ORDER
        if level not in LEGACY_LEVELS or rows[level]['issues'] or level in delays
    ]
    return {'levels': [with_rate(rows[level]) for level in shown], 'total': with_rate(total)}


def compute_actor_stats(issues):
    """Nombre de plaintes par acteur : femmes, hommes, jeunes, réfugiés/PDI. Une plainte peut compter dans
    deux lignes (ex. une jeune femme) ; les pourcentages sont rapportés au total des plaintes."""
    total = len(issues)
    women = men = youth = refugees = gender_unknown = 0
    for issue in issues:
        gender = (issue.gender or '').strip().lower()
        if gender in FEMALE_VALUES:
            women += 1
        elif gender in MALE_VALUES:
            men += 1
        else:
            gender_unknown += 1
        if is_youth_age_group(issue.age_group):
            youth += 1
        if issue.refugee_or_idp:
            refugees += 1

    def line(name, count):
        percentage = round(count * 100 / total) if total else 0
        return {'name': str(name), 'count': count, 'issues': count, 'percentage': percentage}

    return {
        'women': line(_('Women'), women),
        'men': line(_('Men'), men),
        'youth': line(_('Youth (under 35)'), youth),
        'refugees': line(_('Refugees / IDPs'), refugees),
    }, gender_unknown


def filter_diagnostics_issues(request):
    """Filtre commun (start_date / end_date / category / region / wave) partagé par
    `IssuesStatisticsView` et `IssuesMapDataView`, pour que la carte du Togo et les tableaux/
    graphiques réagissent aux mêmes filtres. Retourne `(queryset, wave_administrative_ids)`."""
    get = request.GET
    start_date = get.get('start_date')
    end_date = get.get('end_date')
    # Filtres à choix multiple (MultipleDiagnosticsSearchForm) : une ou plusieurs valeurs.
    category = int_values(get_multiple_values(get, 'category'))
    region = get.get('region')
    waves = get_waves(get)

    queryset = Issue.objects.select_related('status', 'category', 'age_group').filter(confirmed=True, is_deleted=False)

    # Vague(s) : villages de la vague ET période de la vague ; plusieurs vagues = l'une OU
    # l'autre. Avec une seule vague, même résultat qu'avant (les dates saisies, filtrées plus bas,
    # restent bornées par celles de la vague).
    wave_administrative_ids = waves_administrative_ids(waves)
    if waves:
        waves_q = Q()
        for wave_object in waves:
            wave_q = Q(administrative_region_id__in=int_values(wave_object.administrative_ids))
            if wave_object.administrative_ids and wave_object.begin:
                wave_q &= Q(intake_date__gte=datetime.combine(wave_object.begin, datetime.min.time()))
            if wave_object.administrative_ids and wave_object.end:
                wave_q &= Q(intake_date__lte=datetime.combine(wave_object.end, datetime.max.time()))
            waves_q |= wave_q
        queryset = queryset.filter(waves_q)

    if start_date:
        queryset = queryset.filter(intake_date__gte=datetime.strptime(start_date, '%d/%m/%Y'))
    if end_date:
        queryset = queryset.filter(intake_date__lte=datetime.strptime(end_date, '%d/%m/%Y').replace(
            hour=23, minute=59, second=59, microsecond=999999))

    if category:
        queryset = queryset.filter(category__legacy_id__in=category)

    if region:
        filter_regions = get_administrative_level_descendants_using_mis(None, region, [], request.user) + [region]
        if wave_administrative_ids:
            filter_regions = list(set(filter_regions) & set(str(w) for w in wave_administrative_ids))
        filter_regions_int = [int(elt) for elt in filter_regions if str(elt).isdigit()]
        queryset = queryset.filter(administrative_region_id__in=filter_regions_int)

    return queryset, wave_administrative_ids


class IssuesStatisticsView(AJAXRequestMixin, LoginRequiredMixin, JSONResponseMixin, generic.View):
    def get(self, request, *args, **kwargs):
        # Filtre indépendant du "drill-down" par `region` (qui ne fait que restreindre QUELS
        # issues sont pris en compte) : décide à QUEL niveau administratif `region_stats` doit
        # regrouper/afficher les résultats dans #region-stats-container. 'Region' par défaut.
        administrative_level_type = self.request.GET.get('administrative_level_type') or 'Region'
        if administrative_level_type not in ADMINISTRATIVE_LEVEL_TYPES:
            administrative_level_type = 'Region'

        queryset, wave_administrative_ids = filter_diagnostics_issues(request)

        issues = list(queryset)
        total_issues = len(issues)
        region_stats = {}
        region_stats_wave = {}
        status_stats = {}
        type_stats = {}
        category_stats = {}

        def fill_count(key, stats: dict, name=None):
            key = str(key)
            if key in stats:
                stats[key]['count'] = stats[key]['count'] + 1
            else:
                stats[key] = {'count': 1}
            if name:
                stats[key]['name'] = name

        def process_stats(stats: dict):
            for k in stats:
                stats[k]['percentage'] = round(stats[k]['count'] * 100 / total_issues) if total_issues else 0
                stats[k]['issues'] = stats[k]['count']

        def build_ancestor_chain(level):
            """Liste ordonnée [Région, ..., `level`] (`level` inclus) des `{type, name}` de chaque
            ancêtre, du plus haut niveau (Région) au plus fin — permet au frontend de construire
            les colonnes Région/Préfecture/Commune/Canton/Village de #region-stats-container sans
            requête supplémentaire, quel que soit le niveau affiché."""
            chain = []
            node = level
            while node:
                chain.append({'type': node.type, 'name': node.name})
                node = node.parent
            chain.reverse()
            return chain

        def fill_region_name_and_coords(stats: dict):
            if not stats:
                return
            regions = [int(k) for k in stats if str(k).isdigit()]
            levels = mis_objects_call.filter_objects(AdministrativeLevel, id__in=regions)
            for level in levels:
                data = stats.get(str(level.id))
                if data is None:
                    continue
                data['name'] = level.name
                data['latitude'] = float(level.latitude) if level.latitude is not None else None
                data['longitude'] = float(level.longitude) if level.longitude is not None else None
                data['level'] = level.type.capitalize() if level.type else None
                data['ancestors'] = build_ancestor_chain(level)

        for issue in issues:
            if issue.administrative_region_id:
                region_key = get_ancestor_administrative_id_by_type_using_mis(
                    issue.administrative_region_id, administrative_level_type,
                )
                if region_key is not None:
                    fill_count(region_key, region_stats)

                if wave_administrative_ids:
                    fill_count(issue.administrative_region_id, region_stats_wave)

            if issue.status_id:
                fill_count(issue.status.legacy_id, status_stats, issue.status.name)

            if issue.category_id:
                fill_count(issue.category.legacy_id, category_stats, issue.category.name)

        process_stats(region_stats)
        process_stats(region_stats_wave)
        process_stats(status_stats)
        process_stats(type_stats)
        process_stats(category_stats)

        fill_region_name_and_coords(region_stats)
        fill_region_name_and_coords(region_stats_wave)

        # Fill region_stats_wave statistics with wave administrative levels which haven't issues
        if wave_administrative_ids:
            for administrative_id in wave_administrative_ids:
                if str(administrative_id) not in region_stats_wave:
                    region_stats_wave[str(administrative_id)] = {
                        'count': 0,
                        'percentage': 0,
                        'issues': 0,
                    }
            fill_region_name_and_coords(region_stats_wave)

        actor_stats, gender_unknown = compute_actor_stats(issues)
        escalation_stats = compute_escalation_stats(issues)
        deadline_stats = compute_deadline_stats(issues)

        statistics = {
            'actor_stats': actor_stats,
            'escalation_stats': escalation_stats,
            'deadline_stats': deadline_stats,
            'gender_unknown': gender_unknown,
            'region_stats': region_stats,
            'status_stats': status_stats,
            'type_stats': type_stats,
            'category_stats': category_stats,
            'total_issues': total_issues,
            'region_stats_wave': region_stats_wave,
        }
        return self.render_to_json_response(statistics)


class IssuesMapDataView(AJAXRequestMixin, LoginRequiredMixin, JSONResponseMixin, generic.View):
    """Points des plaintes pour la carte du Togo (#diag-map de diagnostics/home.html).

    Une entrée par plainte *localisée* : la plainte est placée sur les coordonnées de son
    village (`administrative_region`), lu depuis la base `mis` — les plaintes dont le village n'a
    pas de latitude/longitude sont ignorées (comptées dans `unlocated`). Le regroupement en
    "grappes" (nombre affiché, éclatement au clic) est fait côté client par Leaflet.markercluster.
    Mêmes filtres que `IssuesStatisticsView` via `filter_diagnostics_issues`."""

    def get(self, request, *args, **kwargs):
        queryset, _wave_ids = filter_diagnostics_issues(request)
        issues = list(queryset.values(
            'tracking_code', 'internal_code', 'administrative_region_id',
            'status__legacy_id', 'status__name', 'category__legacy_id', 'category__name',
        ))

        region_ids = {i['administrative_region_id'] for i in issues if i['administrative_region_id']}
        coords = {}
        if region_ids:
            for level in mis_objects_call.filter_objects(AdministrativeLevel, id__in=list(region_ids)):
                if level.latitude is not None and level.longitude is not None:
                    coords[level.id] = (float(level.latitude), float(level.longitude), level.name)

        points = []
        for i in issues:
            c = coords.get(i['administrative_region_id'])
            if not c:
                continue
            points.append({
                'lat': c[0],
                'lng': c[1],
                'village': c[2],
                'code': i['tracking_code'] or i['internal_code'] or '',
                'category_id': i['category__legacy_id'],
                'category': i['category__name'] or '',
                'status_id': i['status__legacy_id'],
                'status': i['status__name'] or '',
            })

        return self.render_to_json_response({
            'points': points,
            'located': len(points),
            'unlocated': len(issues) - len(points),
            'total': len(issues),
        })


# ---------------------------------------------------------------------------------------------
# Paramétrage des délais de traitement par niveau : réservé au super administrateur.
# ---------------------------------------------------------------------------------------------

class ProcessingDelayAdminMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.is_superuser


ProcessingDelayFormSet = modelformset_factory(
    ProcessingDelay,
    fields=('committee_name', 'delay_days', 'working_days'),
    extra=0,
    widgets={
        'committee_name': forms.TextInput(attrs={'class': 'form-control'}),
        'delay_days': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
    },
)


class ProcessingDelaysView(PageMixin, LoginRequiredMixin, ProcessingDelayAdminMixin, generic.TemplateView):
    template_name = 'diagnostics/processing_delays.html'
    title = _('Processing delays')
    active_level1 = 'processing_delays'

    def _ensure_levels(self):
        for level in ProcessingDelay.LEVEL_ORDER:  # filet de sécurité si la migration de départ manque
            ProcessingDelay.objects.get_or_create(level=level)

    def get_context_data(self, formset=None, **kwargs):
        context = super().get_context_data(**kwargs)
        if formset is None:
            formset = ProcessingDelayFormSet(queryset=ProcessingDelay.objects.filter(is_deleted=False))
            formset.forms.sort(key=lambda f: ProcessingDelay.LEVEL_ORDER.index(f.instance.level)
                               if f.instance.level in ProcessingDelay.LEVEL_ORDER else 99)
        context['formset'] = formset
        return context

    def get(self, request, *args, **kwargs):
        self._ensure_levels()
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        formset = ProcessingDelayFormSet(request.POST, queryset=ProcessingDelay.objects.filter(is_deleted=False))
        if formset.is_valid():
            formset.save()  # `updated_at` avancé : les mobiles reçoivent les délais au prochain pull
            messages.success(request, _('The processing delays have been saved.'))
            return HttpResponseRedirect(reverse('dashboard:diagnostics:processing_delays'))
        return self.render_to_response(self.get_context_data(formset=formset))
