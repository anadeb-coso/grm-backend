from django.urls import path

from issue import views_rest

app_name = 'issue'

urlpatterns = [
    path('save-issue-datas/', views_rest.SaveIssueDatas.as_view(), name='save_issue_datas'),
    path('check-sync-issues/', views_rest.CheckSyncIssues.as_view(), name='check_sync_issues'),
    path('get-issues/', views_rest.RestGetIssues.as_view(), name='get_issues'),
]
