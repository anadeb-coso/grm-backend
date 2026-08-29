from django.urls import path

from dashboard.diagnostics import views

app_name = 'diagnostics'
urlpatterns = [
    path('', views.HomeFormView.as_view(), name='home'),
    path('issues-statistics/', views.IssuesStatisticsView.as_view(), name='issues_statistics'),
    path('issues-map-data/', views.IssuesMapDataView.as_view(), name='issues_map_data'),
]
