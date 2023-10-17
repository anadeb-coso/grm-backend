from django.urls import path

from privacy import views

app_name = 'privacy'
urlpatterns = [
    path('validated-category-password', views.ValidatedMyPasswordByLastCategoryPasswordView.as_view(), name='validated_category_password'),
]