from django.urls import path

from .administrative_levels_views import AdministrativeLevelsView
from .attachment_views import AttachmentDeleteView, AttachmentUploadView
from .views import InactiveDevicesView, PullView, PushView

urlpatterns = [
    path('sync/pull/', PullView.as_view(), name='sync-pull'),
    path('sync/push/', PushView.as_view(), name='sync-push'),
    path('sync/inactive-devices/', InactiveDevicesView.as_view(), name='sync-inactive-devices'),
    path('attachments/', AttachmentUploadView.as_view(), name='sync-attachment-upload'),
    path('attachments/<uuid:pk>/', AttachmentDeleteView.as_view(), name='sync-attachment-delete'),
    path('administrative-levels/', AdministrativeLevelsView.as_view(), name='sync-administrative-levels'),
]
