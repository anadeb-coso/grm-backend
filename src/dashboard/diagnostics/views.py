from datetime import datetime

from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils.translation import gettext_lazy as _
from django.views import generic

from dashboard.grm.forms import SearchIssueForm
from dashboard.mixins import AJAXRequestMixin, JSONResponseMixin, PageMixin
from grm.utils import (
    get_administrative_level_descendants_using_mis, get_ancestor_administrative_id_by_type_using_mis,
)
from grm.call_objects_from_other_db import mis_objects_call
from administrativelevels.models import AdministrativeLevel
from issue.models import Issue, Wave


class HomeFormView(PageMixin, LoginRequiredMixin, generic.FormView):
    form_class = SearchIssueForm
    template_name = 'diagnostics/home.html'
    title = _('Diagnostics')
    active_level1 = 'diagnostics'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context['all_total_issues'] = Issue.objects.filter(confirmed=True, is_deleted=False).count()

        return context


ADMINISTRATIVE_LEVEL_TYPES = ('Region', 'Prefecture', 'Commune', 'Canton', 'Village')


def filter_diagnostics_issues(request):
    """Filtre commun (start_date / end_date / category / region / wave) partagé par
    `IssuesStatisticsView` et `IssuesMapDataView`, pour que la carte du Togo et les tableaux/
    graphiques réagissent aux mêmes filtres. Retourne `(queryset, wave_administrative_ids)`."""
    get = request.GET
    start_date = get.get('start_date')
    end_date = get.get('end_date')
    category = get.get('category')
    region = get.get('region')
    wave = get.get('wave')

    queryset = Issue.objects.select_related('status', 'category').filter(confirmed=True, is_deleted=False)

    wave_administrative_ids = []
    wave_object = None
    if wave:
        wave_object = Wave.objects.filter(id=wave).first()
        if wave_object:
            wave_administrative_ids = wave_object.administrative_ids
            wave_ids_int = [int(elt) for elt in wave_administrative_ids if str(elt).isdigit()]
            queryset = queryset.filter(administrative_region_id__in=wave_ids_int)

    if start_date or wave_administrative_ids:
        if start_date:
            start_date_dt = datetime.strptime(start_date, '%d/%m/%Y')
            if wave_administrative_ids and wave_object and wave_object.begin and wave_object.begin > start_date_dt.date():
                start_date_dt = datetime.combine(wave_object.begin, datetime.min.time())
        elif wave_administrative_ids and wave_object and wave_object.begin:
            start_date_dt = datetime.combine(wave_object.begin, datetime.min.time())
        else:
            start_date_dt = None
        if start_date_dt:
            queryset = queryset.filter(intake_date__gte=start_date_dt)

    if end_date or (wave_administrative_ids and wave_object and wave_object.end):
        if end_date:
            end_date_dt = datetime.strptime(end_date, '%d/%m/%Y').replace(hour=23, minute=59, second=59, microsecond=999999)
            if wave_administrative_ids and wave_object and wave_object.end:
                wave_end_dt = datetime.combine(wave_object.end, datetime.max.time())
                if end_date_dt > wave_end_dt:
                    end_date_dt = wave_end_dt
        elif wave_administrative_ids and wave_object and wave_object.end:
            end_date_dt = datetime.combine(wave_object.end, datetime.max.time())
        else:
            end_date_dt = None
        if end_date_dt:
            queryset = queryset.filter(intake_date__lte=end_date_dt)

    if category:
        queryset = queryset.filter(category__legacy_id=int(category))

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

        statistics = {
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
