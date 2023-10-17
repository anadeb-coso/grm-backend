from django.urls import path

from issue import views_rest

app_name = 'issue'

urlpatterns = [
    path('save-issue-datas/', views_rest.SaveIssueDatas.as_view(), name='save_issue_datas'),
]
