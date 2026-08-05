import os

from celery import Celery
from celery.schedules import crontab

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'grm.settings')

app = Celery('grm')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django apps.
app.autodiscover_tasks()

app.conf.beat_schedule = {
    'cleanup-orphan-attachments-daily': {
        'task': 'issue.tasks.cleanup_orphan_attachments',
        'schedule': crontab(hour=3, minute=0),
    },
    'cleanup-old-tombstones-weekly': {
        'task': 'issue.tasks.cleanup_old_tombstones',
        'schedule': crontab(hour=3, minute=30, day_of_week=0),
    },
}
