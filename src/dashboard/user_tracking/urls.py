from django.urls import path

from dashboard.user_tracking import views

app_name = 'user_tracking'
urlpatterns = [
    path('', views.UserMonitoringView.as_view(), name='home'),
]
