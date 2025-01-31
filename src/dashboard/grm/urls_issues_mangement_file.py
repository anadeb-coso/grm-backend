from django.urls import path

from dashboard.grm import views_issues_mangement_file as views

app_name = 'file'
urlpatterns = [
    path('save-issues/', views.SaveIssuesByFileView.as_view(), name='file_save_issues'),
    path('export/', views.IssuesCSVView.as_view(), name="export_issues_excel"),
]
