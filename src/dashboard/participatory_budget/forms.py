from datetime import datetime

from django import forms
from django.utils.translation import gettext_lazy as _

from grm.utils import get_month_range
from budgeting.models import Phase, Task
from issue.models import Adl


class CommuneSelectForm(forms.Form):
    """« Commune » n'a jamais eu de modèle Postgres dédié (c'était un type de document CouchDB
    séparé dans la base `eadls`, jamais repris lors de la migration mobile) — approximé ici par
    `Adl.department`, le regroupement le plus proche disponible dans le schéma actuel
    (simplification documentée, migration du dashboard web)."""
    commune = forms.ChoiceField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        communes = list(
            Adl.objects.filter(
                department__isnull=False, phases__tasks__isnull=False,
            ).exclude(department='').values_list('department', flat=True).distinct()
        )
        self.fields['commune'].widget.choices = [('', '')] + [(c, c) for c in communes]
        self.fields['commune'].widget.attrs['class'] = 'form-control'


class MonthSelectForm(forms.Form):
    month = forms.ChoiceField(label=_("Show:"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        older_phase_task = Task.objects.select_related('phase').filter(
            phase__open_at__isnull=False,
        ).order_by('phase__open_at').first()
        if older_phase_task:
            start_date = older_phase_task.phase.open_at
            month_range = get_month_range(datetime(start_date.year, start_date.month, 1))
            current_month = month_range[0]
            default_option = [(current_month[0], _("This month"))]
            self.fields['month'].widget.choices = default_option + month_range[1:]
