from django.urls import path

from . import views

app_name = 'internet_credits'
urlpatterns = [
    path('', views.CampaignListView.as_view(), name='list'),
    path('create/', views.CampaignCreateView.as_view(), name='create'),
    path('<uuid:pk>/', views.CampaignDetailView.as_view(), name='detail'),
    path('<uuid:pk>/edit/', views.CampaignUpdateView.as_view(), name='update'),
    path('<uuid:pk>/delete/', views.CampaignDeleteView.as_view(), name='delete'),
    path('<uuid:pk>/refresh/', views.CampaignRefreshView.as_view(), name='refresh'),
    path('<uuid:pk>/export/pdf/', views.MonthlyPdfExportView.as_view(), name='export_pdf'),
    path('<uuid:pk>/export/excel/', views.MonthlyExcelExportView.as_view(), name='export_excel'),
    path('cvd/<uuid:pk>/export/pdf/', views.CvdPdfExportView.as_view(), name='export_cvd_pdf'),
    path('confirmations/<uuid:pk>/reset/', views.ConfirmationResetView.as_view(), name='reset_confirmation'),
    path('confirmations/<uuid:pk>/signature/', views.ConfirmationSignatureView.as_view(), name='signature'),
]
