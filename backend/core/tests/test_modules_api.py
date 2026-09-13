from unittest.mock import patch

from django.test import SimpleTestCase


class ModulesApiTests(SimpleTestCase):
    def test_modules_returns_only_enabled_modules_in_navigation_order(self):
        with patch(
            'core.module_registry.get_list_setting',
            return_value=['stock_moves', 'hundred_day'],
        ):
            response = self.client.get('/api/core/modules/')

        body = response.json()
        modules = body['data']

        self.assertEqual(response.status_code, 200)
        self.assertEqual(body['status'], 'ok')
        self.assertEqual(body['source'], 'application')
        self.assertEqual([module['id'] for module in modules], [
            'stock_moves',
            'hundred_day',
        ])
        self.assertTrue(all(module['enabled'] for module in modules))
        self.assertEqual(modules[0]['display_name'], '大涨跌幅与大成交量个股')
        self.assertEqual(modules[0]['api_prefix'], '/api/stock-moves/')

    def test_health_returns_the_shared_envelope_without_upstream_access(self):
        response = self.client.get('/api/core/health/')
        body = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(body['status'], 'ok')
        self.assertEqual(body['source'], 'application')
        self.assertEqual(body['data'], {'healthy': True})


class DisabledModuleUrlTests(SimpleTestCase):
    """被关掉的模块必须用统一 JSON 外壳自己回答。

    落到 Django 默认 HTML 404 的话，调用方既看不出"模块没启用"（契约里声明的
    ``MODULE_DISABLED``），也拿不到 JSON 外壳，只能靠猜。
    """

    def _urlconf_with(self, enabled: str):
        import importlib
        import os

        with patch.dict(os.environ, {'ENABLED_MODULES': enabled}, clear=False):
            urlconf = importlib.reload(importlib.import_module('backend.urls'))
        # 重载是有全局副作用的（模块对象被就地替换），用完必须按当前 .env 重载回去。
        self.addCleanup(importlib.reload, importlib.import_module('backend.urls'))
        return urlconf

    def test_requests_under_a_disabled_module_get_the_module_disabled_envelope(self):
        from django.test import override_settings

        urlconf = self._urlconf_with('kaipanla')

        with override_settings(ROOT_URLCONF=urlconf):
            response = self.client.get('/api/hundred-day/dates/')

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response['Content-Type'], 'application/json')
        body = response.json()
        self.assertEqual(body['status'], 'error')
        self.assertEqual(body['error']['code'], 'MODULE_DISABLED')
        self.assertIn('百日新高新低占比', body['error']['message'])
        self.assertEqual(body['preparation']['state'], 'unavailable')

    def test_an_enabled_module_prefix_is_not_captured_by_the_disabled_route(self):
        from django.test import override_settings

        urlconf = self._urlconf_with('hundred_day')
        disabled_prefix = '/api/stock-moves/'

        with override_settings(ROOT_URLCONF=urlconf):
            response = self.client.get(disabled_prefix)

        # 反向确认：拿掉一个模块后，另一个（启用的）前缀不会被误判成禁用。
        self.assertEqual(response.json()['error']['code'], 'MODULE_DISABLED')
        self.assertIn('大涨跌幅与大成交量个股', response.json()['error']['message'])
