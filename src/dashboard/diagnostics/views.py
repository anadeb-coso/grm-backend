from datetime import datetime, timedelta

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils.translation import gettext_lazy as _
from django.views import generic

from client import get_db
from dashboard.grm.forms import SearchIssueForm
from dashboard.mixins import AJAXRequestMixin, JSONResponseMixin, PageMixin
from grm.utils import get_administrative_level_descendants, get_base_administrative_id

COUCHDB_GRM_DATABASE = settings.COUCHDB_GRM_DATABASE
COUCHDB_DATABASE_ADMINISTRATIVE_LEVEL = settings.COUCHDB_DATABASE_ADMINISTRATIVE_LEVEL


class HomeFormView(PageMixin, LoginRequiredMixin, generic.FormView):
    form_class = SearchIssueForm
    template_name = 'diagnostics/home.html'
    title = _('Diagnostics')
    active_level1 = 'diagnostics'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['access_token'] = settings.MAPBOX_ACCESS_TOKEN
        context['lat'] = settings.DIAGNOSTIC_MAP_LATITUDE
        context['lng'] = settings.DIAGNOSTIC_MAP_LONGITUDE
        context['zoom'] = settings.DIAGNOSTIC_MAP_ZOOM
        context['ws_bound'] = settings.DIAGNOSTIC_MAP_WS_BOUND
        context['en_bound'] = settings.DIAGNOSTIC_MAP_EN_BOUND
        context['country_iso_code'] = settings.DIAGNOSTIC_MAP_ISO_CODE
        return context


class IssuesStatisticsView(AJAXRequestMixin, LoginRequiredMixin, JSONResponseMixin, generic.View):
    def get(self, request, *args, **kwargs):
        grm_db = get_db(COUCHDB_GRM_DATABASE)
        adl_db = get_db(COUCHDB_DATABASE_ADMINISTRATIVE_LEVEL)

        start_date = self.request.GET.get('start_date')
        end_date = self.request.GET.get('end_date')
        category = self.request.GET.get('category')
        issue_type = self.request.GET.get('type')
        region = self.request.GET.get('region')

        selector = {
            "type": "issue",
            "confirmed": True,
            "auto_increment_id": {"$ne": ""},
        }

        date_range = {}
        if start_date:
            start_date = datetime.strptime(start_date, '%d/%m/%Y').strftime('%Y-%m-%dT%H:%M:%S.%fZ')
            date_range["$gte"] = start_date
            selector["intake_date"] = date_range
        if end_date:
            end_date = (datetime.strptime(end_date, '%d/%m/%Y') + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
            date_range["$lte"] = end_date
            selector["intake_date"] = date_range
        if category:
            selector["category.id"] = int(category)
        if issue_type:
            selector["issue_type.id"] = int(issue_type)

        if region:
            filter_regions = get_administrative_level_descendants(adl_db, region, []) + [region]
            selector["administrative_region.administrative_id"] = {
                "$in": filter_regions
            }

        issues = grm_db.get_query_result(selector)
        issues = [doc for doc in issues]

        total_issues = len(issues)
        region_stats = {}
        status_stats = {}
        type_stats = {}
        category_stats = {}

        def fill_count(key, stats: dict, name=None):
            if key in stats:
                stats[key]['count'] = stats[key]['count'] + 1
            else:
                stats[key] = {
                    'count': 1
                }
            if name:
                stats[key]['name'] = name

        def process_stats(stats: dict):
            for k in stats:
                stats[k]['percentage'] = round(stats[k]['count'] * 100 / total_issues)
                stats[k]['issues'] = stats[k]['count']

        for doc in issues:
            region_key = get_base_administrative_id(adl_db, doc['administrative_region']['administrative_id'], region)
            fill_count(region_key, region_stats)

            status_key = doc['status']['id']
            fill_count(status_key, status_stats, doc['status']['name'])

            type_key = doc['issue_type']['id']
            fill_count(type_key, type_stats, doc['issue_type']['name'])

            category_key = doc['category']['id']
            fill_count(category_key, category_stats, doc['category']['name'])

        process_stats(region_stats)
        process_stats(status_stats)
        process_stats(type_stats)
        process_stats(category_stats)

        regions = [k for k in region_stats]
        selector = {
            "type": "administrative_level",
            "administrative_id": {
                "$in": regions
            }
        }
        administrative_level_docs = adl_db.get_query_result(selector)
        without_administrative_level_docs = True
        for doc in administrative_level_docs:
            without_administrative_level_docs = False
            data = region_stats[doc['administrative_id']]
            data['name'] = doc['name']
            data['latitude'] = doc['latitude']
            data['longitude'] = doc['longitude']
            data['level'] = doc['administrative_level'].capitalize()
        if without_administrative_level_docs:
            region_stats = {}
        statistics = {
            'region_stats': region_stats,
            'status_stats': status_stats,
            'type_stats': type_stats,
            'category_stats': category_stats,
        }
        return self.render_to_json_response(statistics)
