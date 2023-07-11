from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views import generic

from client import get_db
from dashboard.mixins import AJAXRequestMixin, JSONResponseMixin

COUCHDB_GRM_DATABASE = settings.COUCHDB_GRM_DATABASE


class StatisticsOfTasksUpdatedByRegionView(AJAXRequestMixin, LoginRequiredMixin, JSONResponseMixin, generic.View):
    def get(self, request, *args, **kwargs):
        eadl_db = get_db()
        administrative_id = self.request.GET.get('administrative_id', None)
        if administrative_id:
            stats = eadl_db.get_view_result('tasks', 'updated_by_administrative_region_stats',
                                            key=administrative_id)
        else:
            stats = eadl_db.get_view_result('tasks', 'updated_by_administrative_region_stats')

        if stats[0]:
            stats = stats[0][0]['value']
        else:
            stats = {'count': 0}

        return self.render_to_json_response(stats, safe=False)


class IssuesStatisticsView(AJAXRequestMixin, LoginRequiredMixin, JSONResponseMixin, generic.View):
    def get(self, request, *args, **kwargs):
        grm_db = get_db(COUCHDB_GRM_DATABASE)
        
        if hasattr(self.request.user, 'governmentworker') and not self.request.user.groups.filter(name="Admin").exists():
            issues_stats = grm_db.get_view_result('issues', 'by_assignee_stats', key=self.request.user.id)
        else:
            issues_stats = grm_db.get_view_result('issues', 'by_assignee_stats')

        if issues_stats[0]:
            issues_stats = issues_stats[0][0]['value']
        else:
            issues_stats = {'count': 0}

        return self.render_to_json_response(issues_stats, safe=False)
