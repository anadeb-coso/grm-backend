from django.urls import path

from . import views

app_name = 'general'
urlpatterns = [
     path('delete-object/<int:object_id>/<str:type>/', views.DeleteObjectFormView.as_view(), name='object_deletion_form'),
]
