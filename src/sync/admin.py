from datetime import timedelta

from django.contrib import admin
from django.utils import timezone

from .models import SyncLog

INACTIVE_DAYS_THRESHOLD = 30


class InactiveDeviceFilter(admin.SimpleListFilter):
    """CLAUDE.md §9 : « Faire remonter dans un dashboard/log les appareils inactifs depuis plus
    de 30 jours »."""
    title = 'inactivité'
    parameter_name = 'inactive'

    def lookups(self, request, model_admin):
        return [('30', f'Inactif depuis plus de {INACTIVE_DAYS_THRESHOLD} jours')]

    def queryset(self, request, queryset):
        if self.value() == '30':
            cutoff = timezone.now() - timedelta(days=INACTIVE_DAYS_THRESHOLD)
            return queryset.filter(updated_at__lt=cutoff)
        return queryset


@admin.register(SyncLog)
class SyncLogAdmin(admin.ModelAdmin):
    list_display = ('device_id', 'user', 'last_pulled_at', 'last_push_at', 'updated_at')
    list_filter = (InactiveDeviceFilter,)
    search_fields = ('device_id', 'user__email')
    ordering = ('-updated_at',)
    raw_id_fields = ('user',)
