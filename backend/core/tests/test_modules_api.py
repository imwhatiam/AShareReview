from unittest.mock import patch

from django.test import SimpleTestCase


class ModulesApiTests(SimpleTestCase):
    def test_modules_returns_only_enabled_modules_in_navigation_order(self):
        with patch(
            'core.module_registry.get_list_setting',
            return_value=['eastmoney', 'hundred_day'],
        ):
            response = self.client.get('/api/core/modules/')

        body = response.json()
        modules = body['data']

        self.assertEqual(response.status_code, 200)
        self.assertEqual(body['status'], 'ok')
        self.assertEqual(body['source'], 'application')
        self.assertEqual([module['id'] for module in modules], [
            'eastmoney',
            'hundred_day',
        ])
        self.assertTrue(all(module['enabled'] for module in modules))
        self.assertEqual(modules[0]['display_name'], '东方财富')
        self.assertEqual(modules[0]['api_prefix'], '/api/eastmoney/')

    def test_health_returns_the_shared_envelope_without_upstream_access(self):
        response = self.client.get('/api/core/health/')
        body = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(body['status'], 'ok')
        self.assertEqual(body['source'], 'application')
        self.assertEqual(body['data'], {'healthy': True})
