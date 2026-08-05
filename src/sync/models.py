from django.conf import settings
from django.db import models


class SyncLog(models.Model):
    """Bookkeeping serveur (non synchronisé vers le mobile) : une ligne par appareil, mise à
    jour à chaque pull réussi. Sert de base au tableau de bord des appareils inactifs (voir
    CLAUDE.md §9 : "Faire remonter dans un dashboard/log les appareils inactifs depuis plus de
    30 jours")."""
    device_id = models.CharField(max_length=255, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='sync_logs',
    )
    last_pulled_at = models.DateTimeField()
    last_push_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['device_id', 'user']

    def __str__(self):
        return f'{self.device_id} ({self.user})'
