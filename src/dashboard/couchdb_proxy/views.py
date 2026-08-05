from django.contrib.auth.mixins import LoginRequiredMixin
from django.views import generic

from dashboard.mixins import AJAXRequestMixin, JSONResponseMixin
from budgeting.models import Task
from issue.models import Issue


class StatisticsOfTasksUpdatedByRegionView(AJAXRequestMixin, LoginRequiredMixin, JSONResponseMixin, generic.View):
    """Remplace l'ancienne vue CouchDB `tasks/updated_by_administrative_region_stats` (base
    `eadls`) par un comptage Postgres équivalent sur `budgeting.Task`, via le périmètre de
    villages du facilitateur (`Phase.adl.administrative_region_ids`)."""

    def get(self, request, *args, **kwargs):
        administrative_id = self.request.GET.get('administrative_id', None)
        queryset = Task.objects.filter(is_deleted=False)
        if administrative_id:
            try:
                administrative_id_int = int(administrative_id)
            except (TypeError, ValueError):
                administrative_id_int = None
            if administrative_id_int is not None:
                queryset = queryset.filter(
                    phase__adl__administrative_region_ids__contains=[str(administrative_id_int)],
                )
        return self.render_to_json_response({'count': queryset.count()}, safe=False)


class IssuesStatisticsView(AJAXRequestMixin, LoginRequiredMixin, JSONResponseMixin, generic.View):
    """Remplace l'ancienne vue CouchDB `issues/by_assignee_stats` (base `grm`) par un comptage
    Postgres équivalent sur `issue.models.Issue`."""

    def get(self, request, *args, **kwargs):
        queryset = Issue.objects.filter(is_deleted=False)
        if hasattr(self.request.user, 'governmentworker') and not self.request.user.groups.filter(name="Admin").exists():
            queryset = queryset.filter(assignee_id=self.request.user.id)
        return self.render_to_json_response({'count': queryset.count()}, safe=False)
