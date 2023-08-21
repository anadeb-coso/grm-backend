from django.conf.urls import include
from django.urls import path

app_name = 'dashboard'
urlpatterns = [
    path('', include('dashboard.authentication.urls')),
    path('diagnostics/', include('dashboard.diagnostics.urls')),
    path('administrative-levels/', include('dashboard.adls.urls')),
    # path('participatory-budget/', include('dashboard.participatory_budget.urls')),
    # path('subprojects/', include('dashboard.subprojects.urls')),
    path('grm/', include('dashboard.grm.urls')),
    path('logs/', include('dashboard.logs.urls')),
    path('couchdb-proxy/', include('dashboard.couchdb_proxy.urls')),
    path('general/', include('dashboard.general.urls')),
]
