from datetime import datetime, timedelta

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils.translation import gettext_lazy as _
from django.views import generic

from client import get_db
from dashboard.grm.forms import SearchIssueForm
from dashboard.mixins import AJAXRequestMixin, JSONResponseMixin, PageMixin
from grm.utils import (
    get_administrative_level_descendants, get_base_administrative_id, 
    get_administrative_level_descendants_using_mis, get_base_administrative_id_using_mis
)
from issue.models import Wave

COUCHDB_GRM_DATABASE = settings.COUCHDB_GRM_DATABASE
COUCHDB_DATABASE_ADMINISTRATIVE_LEVEL = settings.COUCHDB_DATABASE_ADMINISTRATIVE_LEVEL


class HomeFormView(PageMixin, LoginRequiredMixin, generic.FormView):
    form_class = SearchIssueForm
    template_name = 'diagnostics/home.html'
    title = _('Diagnostics')
    active_level1 = 'diagnostics'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # context['access_token'] = settings.MAPBOX_ACCESS_TOKEN
        # context['lat'] = settings.DIAGNOSTIC_MAP_LATITUDE
        # context['lng'] = settings.DIAGNOSTIC_MAP_LONGITUDE
        # context['zoom'] = settings.DIAGNOSTIC_MAP_ZOOM
        # context['ws_bound'] = settings.DIAGNOSTIC_MAP_WS_BOUND
        # context['en_bound'] = settings.DIAGNOSTIC_MAP_EN_BOUND
        # context['country_iso_code'] = settings.DIAGNOSTIC_MAP_ISO_CODE
        
        grm_db = get_db(COUCHDB_GRM_DATABASE)
        context['all_total_issues'] = len(list(grm_db.get_query_result({
                "type": "issue",
                "confirmed": True,
                "auto_increment_id": {"$ne": ""},
            })))
        
        return context


class IssuesStatisticsView(AJAXRequestMixin, LoginRequiredMixin, JSONResponseMixin, generic.View):
    def get(self, request, *args, **kwargs):
        grm_db = get_db(COUCHDB_GRM_DATABASE)
        adl_db = get_db(COUCHDB_DATABASE_ADMINISTRATIVE_LEVEL)

        start_date = self.request.GET.get('start_date')
        end_date = self.request.GET.get('end_date')
        category = self.request.GET.get('category')
        # issue_type = self.request.GET.get('type')
        region = self.request.GET.get('region')
        wave = self.request.GET.get('wave')

        selector = {
            "type": "issue",
            "confirmed": True,
            "auto_increment_id": {"$ne": ""},
        }

        wave_administrative_ids = []
        if wave:
            wave_object = Wave.objects.filter(id=wave).first()
            if wave_object:
                wave_administrative_ids = wave_object.administrative_ids
                selector["administrative_region.administrative_id"] = {
                    "$in": wave_administrative_ids + [int(elt) for elt in wave_administrative_ids if isinstance(elt, str) and elt.isdigit() and int(elt) not in wave_administrative_ids]
                }

        if start_date or wave_administrative_ids:
            if start_date:
                start_date = datetime.strptime(start_date, '%d/%m/%Y').strftime('%Y-%m-%dT%H:%M:%S.%fZ')
                if wave_administrative_ids:
                    wave_begin_date = wave_object.begin.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
                    if start_date < wave_begin_date:
                        start_date = wave_begin_date
            elif wave_administrative_ids:
                start_date = wave_object.begin.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
            selector["intake_date"] = {"$gte": start_date}
        if end_date or (wave_administrative_ids and wave_object.end):
            if end_date:
                # end_date = datetime.strptime(end_date, '%d/%m/%Y').strftime('%Y-%m-%dT%23:59:59.999999Z') #(datetime.strptime(end_date, '%d/%m/%Y') + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
                end_date = datetime.strptime(end_date, '%d/%m/%Y').replace(
                    hour=23,
                    minute=59,
                    second=59,
                    microsecond=999999
                ).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                if wave_administrative_ids and wave_object and wave_object.end:
                    wave_end_date = wave_object.end.replace(
                        hour=23,
                        minute=59,
                        second=59,
                        microsecond=999999
                    ).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                    if end_date > wave_end_date:
                        end_date = wave_end_date
            elif wave_administrative_ids and wave_object and wave_object.end:
                end_date = wave_object.end.replace(
                    hour=23,
                    minute=59,
                    second=59,
                    microsecond=999999
                ).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                
            if "intake_date" not in selector:
                selector["intake_date"] = {"$lte": end_date}
            else:
                selector["intake_date"]["$lte"] = end_date
        
        if category:
            selector["category.id"] = int(category)
        # if issue_type:
        #     selector["issue_type.id"] = int(issue_type)

        if region:
            # filter_regions = get_administrative_level_descendants(adl_db, region, []) + [region]
            filter_regions = get_administrative_level_descendants_using_mis(adl_db, region, [], request.user) + [region]
            if wave_administrative_ids:
                filter_regions = list(set(filter_regions) & set(wave_administrative_ids))
            selector["administrative_region.administrative_id"] = {
                "$in": filter_regions + [int(elt) for elt in filter_regions if isinstance(elt, str) and elt.isdigit() and int(elt) not in filter_regions]
            }

        issues = grm_db.get_query_result(selector)
        issues = [doc for doc in issues]

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
                stats[key] = {
                    'count': 1
                }
            if name:
                stats[key]['name'] = name

        def process_stats(stats: dict):
            for k in stats:
                k = str(k)
                stats[k]['percentage'] = round(stats[k]['count'] * 100 / total_issues)
                stats[k]['issues'] = stats[k]['count']
        
        def fill_region_name_and_coords(stats: dict):
            regions = [str(k) for k in stats]
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
                data = stats[doc['administrative_id']]
                data['name'] = doc['name']
                data['latitude'] = doc['latitude']
                data['longitude'] = doc['longitude']
                data['level'] = doc['administrative_level'].capitalize()
            if without_administrative_level_docs:
                stats = {}


        for doc in issues:
            if 'administrative_region' in doc and 'administrative_id' in doc['administrative_region']:
                # region_key = get_base_administrative_id(adl_db, doc['administrative_region']['administrative_id'], region)
                region_key = get_base_administrative_id_using_mis(doc['administrative_region']['administrative_id'], region)
                fill_count(region_key, region_stats)

                if wave_administrative_ids:
                    fill_count(doc['administrative_region']['administrative_id'], region_stats_wave)
                

            status_key = doc['status']['id']
            fill_count(status_key, status_stats, doc['status']['name'])

            # type_key = doc['issue_type']['id']
            # fill_count(type_key, type_stats, doc['issue_type']['name'])

            category_key = doc['category']['id']
            fill_count(category_key, category_stats, doc['category']['name'])

        process_stats(region_stats)
        process_stats(region_stats_wave)
        process_stats(status_stats)
        process_stats(type_stats)
        process_stats(category_stats)

        fill_region_name_and_coords(region_stats)
        fill_region_name_and_coords(region_stats_wave)



        #'1955': {'count': 10, 'percentage': 62, 'issues': 10, 'name': 'KETAO', 'latitude': None, 'longitude': None, 'level': 'Village'}
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
        

        # Sort region_stats and region_stats_wave by count descending
        # region_stats = dict(sorted(region_stats.items(), key=lambda item: item[1]['count'], reverse=True))
        # region_stats_wave = dict(sorted(region_stats_wave.items(), key=lambda item: item[1]['count'], reverse=True))

        statistics = {
            'region_stats': region_stats,
            'status_stats': status_stats,
            'type_stats': type_stats,
            'category_stats': category_stats,
            'total_issues': total_issues,
            'region_stats_wave': region_stats_wave,
        }
        return self.render_to_json_response(statistics)
