from django.urls import reverse

from administrativelevels.models import AdministrativeLevel
from dashboard.diagnostics.views import HomeFormView
from grm.tests import DashboardTestCase


class TestHomeTemplateView(DashboardTestCase):
    # Le formulaire de recherche lit les régions dans la base `mis` (base de test dédiée, cf.
    # grm/test_settings.py et src/conftest.py).
    databases = {'default', 'mis'}

    def setUp(self):
        super().setUp()
        self.url = reverse('dashboard:diagnostics:home')
        # SearchIssueForm lit le premier niveau sous le pays racine pour libeller le filtre
        # « Région » : la base `mis` de test est vide, on y crée ce référentiel minimal.
        country = AdministrativeLevel.objects.create(name='TOGO', type='Country')
        AdministrativeLevel.objects.create(name='SAVANES', type='Region', parent=country)

    def test_auth_permission(self):
        response = self.get(self.url, authorized=False)

        assert response.status_code == 302

    def test_context_data(self):
        # Requêtes sur la base `default` uniquement (création de l'utilisateur de test, session,
        # contrôles de groupe du menu/en-tête : nombre fixe, indépendant du volume de données).
        # L'ancienne valeur (18) datait de l'époque CouchDB.
        with self.assertNumQueries(59):
            response = self.get(self.url)
        context_data = response.context_data

        assert response.status_code == 200
        assert context_data['title'] == HomeFormView.title == 'Diagnostics'
        assert context_data['active_level1'] == HomeFormView.active_level1 == 'diagnostics'
        assert context_data['active_level2'] == HomeFormView.active_level2 is None
        assert context_data['breadcrumb'] == HomeFormView.breadcrumb is None
        assert isinstance(context_data['view'], HomeFormView)
