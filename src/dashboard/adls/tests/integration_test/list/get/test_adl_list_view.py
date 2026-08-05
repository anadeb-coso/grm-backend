from django.urls import reverse
from parameterized import parameterized

from authentication.tests import AdlFactory
from dashboard.adls.views import AdlListView
from grm.tests import DashboardTestCase


class TestAdlListView(DashboardTestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse('dashboard:adls:list')

    def test_auth_permission(self):
        response = self.get(self.url, authorized=False)

        assert response.status_code == 302

    def test_context_data(self):
        adls = AdlFactory.create_batch(4)

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
        assert context_data['object_list'] == context_data['adls']
        assert {doc['_id'] for doc in context_data['adls']} == {str(adl.pk) for adl in adls}
        assert isinstance(context_data['view'], AdlListView)

    @parameterized.expand([
        (1,),
        (3,),
        (5,),
    ])
    def test_adls_list(self, size):
        adls = AdlFactory.create_batch(size)

        response = self.get(self.url)
        context_data = response.context_data

        assert response.status_code == 200
        assert context_data['object_list'] == context_data['adls']
        assert {doc['_id'] for doc in context_data['adls']} == {str(adl.pk) for adl in adls}
