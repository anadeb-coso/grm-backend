from django.urls import path

from . import views

app_name = 'service_api'

urlpatterns = [
    path('adls/', views.AdlListView.as_view(), name='adl-list'),
    path('adls/by-email/', views.AdlByEmailView.as_view(), name='adl-by-email'),
    path('adls/by-village/', views.AdlByVillageView.as_view(), name='adl-by-village'),
    path('adls/villages-with-adls/', views.VillagesWithAdlsView.as_view(), name='villages-with-adls'),
    path('users/set-password/', views.SetUserPasswordView.as_view(), name='set-user-password'),
    path('issue-categories/', views.IssueCategoryListView.as_view(), name='issue-categories'),
    path('issue-statuses/', views.IssueStatusListView.as_view(), name='issue-statuses'),
    path('issues/', views.IssueListView.as_view(), name='issues'),
    path('issues/stats/by-assignee/', views.IssueStatsByAssigneeView.as_view(), name='issues-stats-by-assignee'),
]
