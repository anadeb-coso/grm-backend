import uuid

from django.contrib.auth.models import Group
from django.urls import reverse, reverse_lazy

from authentication.tests import AdlFactory, UserFactory
from dashboard.adls.views import AdlDetailView
from grm.tests import DashboardTestCase


class TestAdlDetailView(DashboardTestCase):
    # Le profil résout les niveaux administratifs dans `mis` (base de test dédiée, cf.
    # grm/test_settings.py et src/conftest.py).
    databases = {'default', 'mis'}

    def setUp(self):
        super().setUp()
        self.adl = AdlFactory()
        self.url = reverse('dashboard:adls:detail', kwargs={'id': self.adl.pk})
        # Page réservée aux comptes ayant un groupe (ADLMixin -> SpecificPermissionRequiredMixin).
        self.user = UserFactory()
        self.user.groups.add(Group.objects.get_or_create(name='Admin')[0])

    def test_user_without_group_is_forbidden(self):
        response = self.get(self.url, user=UserFactory())

        assert response.status_code == 403

    def test_auth_permission(self):
        response = self.get(self.url, authorized=False)

        assert response.status_code == 302

    def test_context_data(self):
        response = self.get(self.url)
        context_data = response.context_data

        assert response.status_code == 200
        assert context_data['title'] == AdlDetailView.title == 'Facilitator Profile'
        assert context_data['active_level1'] == AdlDetailView.active_level1 == 'adls'
        assert context_data['active_level2'] == AdlDetailView.active_level2 is None
        assert len(context_data['breadcrumb']) == 2
        assert context_data['breadcrumb'][0]['url'] == AdlDetailView.breadcrumb[0]['url'] == reverse_lazy(
            'dashboard:adls:list')
        assert context_data['breadcrumb'][0]['title'] == AdlDetailView.breadcrumb[0]['title'] == 'Administrative Levels'
        assert context_data['breadcrumb'][1]['url'] == AdlDetailView.breadcrumb[1]['url'] == ''
        assert context_data['breadcrumb'][1]['title'] == AdlDetailView.breadcrumb[1][
            'title'] == AdlDetailView.title
        assert context_data['object']['_id'] == context_data['adl']['_id'] == str(self.adl.pk)
        assert isinstance(context_data['view'], AdlDetailView)

    def test_non_existent_adl(self):
        url = reverse('dashboard:adls:detail', kwargs={'id': uuid.uuid4()})
        response = self.get(url)

        assert response.status_code == 404
