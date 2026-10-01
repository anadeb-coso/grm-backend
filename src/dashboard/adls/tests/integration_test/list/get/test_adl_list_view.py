from django.contrib.auth.models import Group
from django.urls import reverse
from parameterized import parameterized

from authentication.tests import AdlFactory, UserFactory
from dashboard.adls.views import AdlListView
from grm.tests import DashboardTestCase
from issue.models import Adl


class TestAdlListView(DashboardTestCase):
    """La page est réservée aux comptes ayant un groupe (SpecificPermissionRequiredMixin) et ne
    transporte plus la liste dans son contexte : les lignes sont servies page par page par
    `AdlListDatatableJsonView` (DataTables `serverSide`), cf. dashboard/adls/views.py."""
    # Le formulaire de création de profil lit les niveaux administratifs dans `mis` (base de test
    # dédiée, cf. grm/test_settings.py et src/conftest.py).
    databases = {'default', 'mis'}

    def setUp(self):
        super().setUp()
        self.url = reverse('dashboard:adls:list')
        self.datatable_url = reverse('dashboard:adls:list_datatable')
        self.user = UserFactory()
        self.user.groups.add(Group.objects.get_or_create(name='Admin')[0])

    def test_auth_permission(self):
        response = self.get(self.url, authorized=False)

        assert response.status_code == 302

    def test_user_without_group_is_forbidden(self):
        response = self.get(self.url, user=UserFactory())

        assert response.status_code == 403

    def test_context_data(self):
        AdlFactory.create_batch(4)

        response = self.get(self.url)
        context_data = response.context_data

        assert response.status_code == 200
        assert context_data['title'] == AdlListView.title == 'Administrative Levels'
        assert context_data['active_level1'] == AdlListView.active_level1 == 'adls'
        assert context_data['active_level2'] == AdlListView.active_level2 is None
        assert len(context_data['breadcrumb']) == 1
        assert context_data['breadcrumb'][0]['url'] == AdlListView.breadcrumb[0]['url'] == ''
        assert context_data['breadcrumb'][0]['title'] == AdlListView.breadcrumb[0]['title'] == AdlListView.title
        assert context_data['paginator'] == context_data['page_obj'] is None
        assert context_data['is_paginated'] is False
        assert list(context_data['adls']) == []  # lignes chargées par l'endpoint datatable
        assert isinstance(context_data['view'], AdlListView)

    @parameterized.expand([
        (1,),
        (3,),
        (5,),
    ])
    def test_adls_list(self, size):
        adls = AdlFactory.create_batch(size)

        response = self.get(self.datatable_url, {'draw': 1, 'start': 0, 'length': -1})
        data = response.json()

        assert response.status_code == 200
        # Chaque création de `User` crée aussi son `Adl` (signal), y compris l'utilisateur de test.
        assert data['recordsTotal'] == Adl.objects.count()
        listed = {row['DT_RowAttr']['data-href'] for row in data['data']}
        assert {reverse('dashboard:adls:detail', args=[str(adl.pk)]) for adl in adls} <= listed
