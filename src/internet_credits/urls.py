from django.urls import path

from .api_views import ConfirmationCreateView, NotificationListView

urlpatterns = [
    path('notifications/', NotificationListView.as_view(), name='internet-credit-notifications'),
    path('confirmations/', ConfirmationCreateView.as_view(), name='internet-credit-confirmations'),
]
