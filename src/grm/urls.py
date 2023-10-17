"""grm URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/3.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.conf.urls import include
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import path
from drf_yasg import openapi
from drf_yasg.views import get_schema_view
from rest_framework import permissions
from django.conf.urls.i18n import i18n_patterns
from .views import set_language

handler400 = 'dashboard.authentication.views.handler400'
handler403 = 'dashboard.authentication.views.handler403'
handler404 = 'dashboard.authentication.views.handler404'
handler500 = 'dashboard.authentication.views.handler500'

urlpatterns = [
    path('set-language/', set_language, name='set_language'),
    # path('admin/', admin.site.urls),
    path('attachments/', include('attachments.urls')),
    path('authentication/', include('authentication.urls')),
    path('i18n/', include('django.conf.urls.i18n')),
    # path('', include('dashboard.urls')),
    path('administrative-levels/', include('administrativelevels.urls')),
    path('privacy/', include('privacy.urls')),
    path('issue/', include('issue.urls')),
]

schema_view = get_schema_view(
    openapi.Info(
        title="GRM API Documentation",
        default_version='v1',
        description="Test Documentation",
    ),
    public=True,
    permission_classes=(permissions.AllowAny,),
)

urlpatterns += staticfiles_urlpatterns()

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += [
        path('swagger/', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),
    ]

urlpatterns += i18n_patterns(
    path('admin/', admin.site.urls),
    path('', include('dashboard.urls')),
)