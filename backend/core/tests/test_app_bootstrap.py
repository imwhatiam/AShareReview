from django.test import SimpleTestCase
from django.urls import resolve


class CoreAppBootstrapTests(SimpleTestCase):
    def test_health_endpoint_is_available_without_login(self):
        response = self.client.get('/api/core/health/')

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content,
            {
                'status': 'ok',
                'business_date': None,
                # 健康检查不服务任何数据，所以没有"数据写入时刻"。
                'data_updated_at': None,
                'stale': False,
                'source': 'application',
                'preparation': {
                    'state': 'ready',
                    'retry_after_seconds': None,
                },
                'warnings': [],
                'error': None,
                # 与 generated_at 同理：交易日覆盖边界随依赖版本和当前年份变，
                # 这条用例只钉外壳形状，取值由 test_calendar_services 钉。
                'data': {
                    'healthy': True,
                    'trading_calendar': response.json()['data']['trading_calendar'],
                },
                'generated_at': response.json()['generated_at'],
            },
        )

    def test_unknown_api_path_returns_not_found(self):
        response = self.client.get('/api/not-a-module/')

        self.assertEqual(response.status_code, 404)

    def test_health_url_is_owned_by_core(self):
        match = resolve('/api/core/health/')

        self.assertEqual(match.namespace, 'core')
