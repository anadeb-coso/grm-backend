from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from issue.models import Attachment, Comment, Issue, IssueStatusStory, Reason

ORPHAN_ATTACHMENT_MAX_AGE = timedelta(days=7)  # fichier jamais lié à une issue

TOMBSTONED_MODELS = [Issue, Comment, IssueStatusStory, Reason, Attachment]


@shared_task
def cleanup_orphan_attachments():
    """Supprime les fichiers uploadés mais jamais rattachés à une issue (upload interrompu,
    formulaire abandonné, etc.)."""
    cutoff = timezone.now() - ORPHAN_ATTACHMENT_MAX_AGE
    orphans = Attachment.objects.filter(issue__isnull=True, created_at__lt=cutoff, is_deleted=False)
    count = orphans.count()
    for attachment in orphans:
        attachment.file.delete(save=False)
    # `updated_at` doit être forcé explicitement : `QuerySet.update()` n'applique jamais `auto_now`
    # (contrairement à `Model.save()`) — sans lui, ce nettoyage restait invisible au pull mobile.
    orphans.update(is_deleted=True, updated_at=timezone.now())
    return f'{count} pièces jointes orphelines nettoyées'


@shared_task
def cleanup_old_tombstones():
    """Purge définitivement les enregistrements marqués `is_deleted=True` depuis plus de
    `TOMBSTONE_MAX_AGE_DAYS`. ⚠️ Ne fonctionne correctement que si tous les clients mobiles ont eu
    l'occasion de synchroniser la suppression dans cet intervalle — sinon `sync.views.PullView`
    bascule automatiquement ces clients en `force_full_resync` plutôt que de leur faire manquer
    la suppression."""
    cutoff = timezone.now() - timedelta(days=settings.TOMBSTONE_MAX_AGE_DAYS)
    total_deleted = 0
    for Model in TOMBSTONED_MODELS:
        qs = Model.objects.filter(is_deleted=True, updated_at__lt=cutoff)
        total_deleted += qs.count()
        if Model is Attachment:
            for attachment in qs:
                attachment.file.delete(save=False)
        qs.delete()
    return f'{total_deleted} tombstones purgés définitivement'
