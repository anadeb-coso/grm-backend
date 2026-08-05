from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils.translation import gettext_lazy as _
from django.views import generic

from dashboard.mixins import AJAXRequestMixin, PageMixin
from dashboard.participatory_budget.forms import CommuneSelectForm, MonthSelectForm
from grm.utils import sort_dictionary_list_by_field
from budgeting.models import Phase, Task
from issue.models import Adl


class DashboardTemplateView(PageMixin, LoginRequiredMixin, generic.TemplateView):
    template_name = 'participatory_budget/dashboard.html'
    title = _('Participatory Budget')
    active_level1 = 'participatory_budget'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # cf. dashboard/participatory_budget/forms.py::CommuneSelectForm — « commune » approximé
        # par `Adl.department`, faute de modèle Postgres dédié.
        all_communes = Adl.objects.filter(department__isnull=False).exclude(department='').values_list(
            'department', flat=True,
        ).distinct()
        served_communes = Adl.objects.filter(
            department__isnull=False, phases__tasks__isnull=False,
        ).exclude(department='').values_list('department', flat=True).distinct()
        context['communes_served'] = served_communes.count()
        context['total_communes'] = all_communes.count()
        context['commune_select_form'] = CommuneSelectForm()
        context['month_select_form'] = MonthSelectForm()
        return context


class UpdatedTaskListView(AJAXRequestMixin, LoginRequiredMixin, generic.ListView):
    template_name = 'participatory_budget/task_list.html'
    context_object_name = 'tasks'

    def get_queryset(self):
        index = int(self.request.GET.get('index'))
        offset = int(self.request.GET.get('offset'))
        commune = self.request.GET.get('commune', None)
        queryset = Task.objects.select_related('phase', 'phase__adl').filter(is_deleted=False)
        if commune:
            queryset = queryset.filter(phase__adl__department=commune)
        return list(queryset.order_by('-updated_at')[index:index + offset])


class StatementListView(AJAXRequestMixin, LoginRequiredMixin, generic.ListView):
    template_name = 'participatory_budget/statement.html'
    context_object_name = 'phases'

    def get_queryset(self):
        month = self.request.GET.get('month', None).split('-')
        year = int(month[0])
        month = int(month[1])

        # Équivalent Postgres de l'ancienne vue CouchDB `phases/tasks_by_month` : regroupe les
        # tâches par phase pour le mois donné (basé sur `Phase.open_at`), calcule le taux de
        # complétion — reconstruction fidèle à l'intention plutôt que portage à l'identique d'une
        # fonction map/reduce CouchDB non inspectable (simplification documentée).
        phases = Phase.objects.filter(
            open_at__year=year, open_at__month=month, is_deleted=False,
        ).prefetch_related('tasks')

        result = []
        for phase in phases:
            tasks = [t for t in phase.tasks.all() if not t.is_deleted]
            total_tasks = len(tasks)
            completed_tasks = len([t for t in tasks if t.status == Task.STATUS_COMPLETED])
            performance = round(completed_tasks * 100 / total_tasks) if total_tasks else 0
            result.append({
                "title": phase.title,
                "performance": performance,
                "completed_tasks": completed_tasks,
            })
        return sort_dictionary_list_by_field(result, 'performance', True)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['colors'] = [
            'gray', 'lightgray', 'mediumpurple', 'plum', 'mediumslateblue', 'warning', 'primary', 'danger']
        return context
