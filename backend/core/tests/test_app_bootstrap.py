from django.test import SimpleTestCase
from django.urls import resolve


class CoreAppBootstrapTests(SimpleTestCase):
    def test_health_endpoint_is_available_without_login(self):
        response = self.client.get('/api/core/health/')

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {'status': 'ok'})

    def test_unknown_api_path_returns_not_found(self):
        response = self.client.get('/api/not-a-module/')

        self.assertEqual(response.status_code, 404)

    def test_health_url_is_owned_by_core(self):
        match = resolve('/api/core/health/')

        self.assertEqual(match.namespace, 'core')
