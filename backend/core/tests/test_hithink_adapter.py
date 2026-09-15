from datetime import date
from decimal import Decimal
from unittest.mock import patch

import requests
from django.test import SimpleTestCase


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class RecordingTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, *, headers, params, timeout):
        self.calls.append({
            'url': url,
            'headers': headers,
            'params': params,
            'timeout': timeout,
        })
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class HithinkAdapterTests(SimpleTestCase):
    def setUp(self):
        self.settings = {
            'HITHINK_FINANCE_BASE_URL': 'https://hithink.test',
            'HITHINK_FINANCE_API_KEY': 'test-api-key',
            'HITHINK_FINANCE_TIMEOUT_SECONDS': '7',
            'HITHINK_FINANCE_REQUEST_DELAY_SECONDS': '0',
            'HITHINK_FINANCE_MAX_RETRIES': '0',
        }

    def test_list_a_share_tickers_maps_stock_contract_and_request(self):
        from core.integrations.hithink.client import HithinkClient

        transport = RecordingTransport([
            FakeResponse(200, {
                'code': 0,
                'message': 'ok',
                'request_id': 'request-1',
                'data': {
                    'item': [{
                        'thscode': '000001.SZ',
                        'ticker': '000001',
                        'name': '平安银行',
                        'exchange': 'SZ',
                        'asset_type': 'a-share',
                    }],
                },
            }),
        ])

        with patch.dict('os.environ', self.settings, clear=False):
            tickers = HithinkClient(transport=transport).list_a_share_tickers(
                limit=1000,
                offset=0,
            )

        self.assertEqual(len(tickers), 1)
        self.assertEqual(tickers[0].thscode, '000001.SZ')
        self.assertEqual(tickers[0].stock_code, '000001')
        self.assertEqual(tickers[0].stock_name, '平安银行')
        self.assertEqual(tickers[0].exchange, 'szse')
        self.assertEqual(transport.calls[0]['url'],
                         'https://hithink.test/api/meta/tickers/list')
        self.assertEqual(transport.calls[0]['headers']['X-api-key'], 'test-api-key')
        self.assertEqual(transport.calls[0]['params'], {
            'asset_type': 'a-share',
            'exchange': 'SH,SZ,BJ',
            'limit': 1000,
            'offset': 0,
        })
        self.assertEqual(transport.calls[0]['timeout'], 7)

    def test_get_historical_prices_uses_fixed_daily_forward_adjustment(self):
        from core.integrations.hithink.client import HithinkClient

        transport = RecordingTransport([
            FakeResponse(200, {
                'code': 0,
                'data': {
                    'item': [{
                        'date_ms': 1788796800000,
                        'open_price': 10.1,
                        'high_price': 10.3,
                        'low_price': 10.0,
                        'close_price': 10.2,
                        'volume': 1000,
                        'turnover': 10200.5,
                    }],
                },
            }),
        ])

        with patch.dict('os.environ', self.settings, clear=False):
            prices = HithinkClient(transport=transport).get_historical_prices(
                '000001.SZ',
                start_date=date(2026, 9, 8),
                end_date=date(2026, 9, 8),
            )

        self.assertEqual(prices[0].trade_date, date(2026, 9, 8))
        self.assertEqual(prices[0].open_price, Decimal('10.1'))
        self.assertEqual(prices[0].close_price, Decimal('10.2'))
        self.assertEqual(prices[0].volume, 1000)
        self.assertEqual(prices[0].turnover, Decimal('10200.5'))
        self.assertEqual(transport.calls[0]['params'], {
            'thscode': '000001.SZ',
            'interval': '1d',
            'start': 1788796800000,
            'end': 1788796800000,
            'adjust': 'forward',
            'offset': 0,
        })

    def test_list_market_quotes_pages_the_whole_market_and_keeps_nulls(self):
        """停牌股的价格字段必须原样保留为 null，由服务层转成“无成交”。"""
        from core.integrations.hithink.client import HithinkClient

        transport = RecordingTransport([
            FakeResponse(200, {
                'code': 0,
                'data': {
                    'timestamp': 1788796800000,
                    'total': 5571,
                    'item': [
                        {
                            'thscode': '000001.SZ',
                            'ticker': '000001',
                            'last_price': 10.2,
                            'price_change': 0.2,
                            'price_change_ratio_pct': 2.0,
                            'open_price': 10.1,
                            'high_price': 10.3,
                            'low_price': 10.0,
                            'prev_price': 10.0,
                            'volume': 1000,
                            'turnover': 10200.5,
                        },
                        {
                            'thscode': '600000.SH',
                            'ticker': '600000',
                            'last_price': None,
                            'open_price': None,
                            'high_price': None,
                            'low_price': None,
                            'prev_price': 20.0,
                            'volume': 0,
                            'turnover': 0,
                        },
                    ],
                },
            }),
        ])

        with patch.dict('os.environ', self.settings, clear=False):
            quotes, total = HithinkClient(transport=transport).list_market_quotes(
                limit=1000,
                offset=0,
            )

        self.assertEqual(total, 5571)
        self.assertEqual(len(quotes), 2)
        self.assertEqual(quotes[0].thscode, '000001.SZ')
        self.assertEqual(quotes[0].last_price, Decimal('10.2'))
        self.assertEqual(quotes[0].turnover, Decimal('10200.5'))
        self.assertIsNone(quotes[1].last_price)
        self.assertIsNone(quotes[1].open_price)
        self.assertEqual(quotes[1].thscode, '600000.SH')
        self.assertEqual(
            transport.calls[0]['url'],
            'https://hithink.test/api/a-share/prices/snapshot',
        )
        self.assertEqual(transport.calls[0]['params'], {'limit': 1000, 'offset': 0})

    def test_list_market_quotes_rejects_a_pagination_outside_the_upstream_range(self):
        from core.integrations.hithink.client import HithinkClient

        with patch.dict('os.environ', self.settings, clear=False):
            client = HithinkClient(transport=RecordingTransport([]))
            with self.assertRaises(ValueError):
                client.list_market_quotes(limit=0, offset=0)
            with self.assertRaises(ValueError):
                client.list_market_quotes(limit=1000, offset=-1)

    def test_get_historical_prices_accepts_integral_float_volume_from_upstream(self):
        from core.integrations.hithink.client import HithinkClient

        transport = RecordingTransport([
            FakeResponse(200, {
                'code': 0,
                'data': {
                    'item': [{
                        'date_ms': 1788796800000,
                        'open_price': 10.1,
                        'high_price': 10.3,
                        'low_price': 10.0,
                        'close_price': 10.2,
                        'volume': 1000.0,
                        'turnover': 10200.5,
                    }],
                },
            }),
        ])

        with patch.dict('os.environ', self.settings, clear=False):
            prices = HithinkClient(transport=transport).get_historical_prices(
                '000001.SZ',
                start_date=date(2026, 9, 8),
                end_date=date(2026, 9, 8),
            )

        self.assertEqual(prices[0].volume, 1000)


    def test_missing_required_ticker_field_is_rejected(self):
        from core.integrations.hithink.client import HithinkClient
        from core.integrations.hithink.contracts import HithinkPayloadError

        transport = RecordingTransport([
            FakeResponse(200, {
                'code': 0,
                'data': {'item': [{'ticker': '000001', 'name': '平安银行'}]},
            }),
        ])

        with patch.dict('os.environ', self.settings, clear=False):
            with self.assertRaises(HithinkPayloadError):
                HithinkClient(transport=transport).list_a_share_tickers(
                    limit=1000,
                    offset=0,
                )

    def test_invalid_historical_number_is_rejected(self):
        from core.integrations.hithink.client import HithinkClient
        from core.integrations.hithink.contracts import HithinkPayloadError

        transport = RecordingTransport([
            FakeResponse(200, {
                'code': 0,
                'data': {
                    'item': [{
                        'date_ms': 1788796800000,
                        'open_price': 'not-a-number',
                        'high_price': 10.3,
                        'low_price': 10.0,
                        'close_price': 10.2,
                        'volume': 1000,
                        'turnover': 10200,
                    }],
                },
            }),
        ])

        with patch.dict('os.environ', self.settings, clear=False):
            with self.assertRaises(HithinkPayloadError):
                HithinkClient(transport=transport).get_historical_prices(
                    '000001.SZ',
                    start_date=date(2026, 9, 8),
                    end_date=date(2026, 9, 8),
                )

    def test_rate_limit_and_authentication_failures_have_distinct_types(self):
        from core.integrations.hithink.client import HithinkClient
        from core.integrations.hithink.contracts import (
            HithinkAuthenticationError,
            HithinkRateLimitError,
        )

        with patch.dict('os.environ', self.settings, clear=False):
            with self.assertRaises(HithinkRateLimitError):
                HithinkClient(transport=RecordingTransport([
                    FakeResponse(429, {'code': 4001, 'data': None}),
                ])).list_a_share_tickers(limit=1, offset=0)
            with self.assertRaises(HithinkAuthenticationError):
                HithinkClient(transport=RecordingTransport([
                    FakeResponse(200, {'code': 2003, 'data': None}),
                ])).list_a_share_tickers(limit=1, offset=0)

    def test_transport_timeout_is_mapped_to_upstream_unavailable(self):
        from core.integrations.hithink.client import HithinkClient
        from core.integrations.hithink.contracts import HithinkUnavailableError

        transport = RecordingTransport([requests.Timeout('timed out')])

        with patch.dict('os.environ', self.settings, clear=False):
            with self.assertRaises(HithinkUnavailableError):
                HithinkClient(transport=transport).list_a_share_tickers(limit=1, offset=0)

    def test_list_industry_indices_requests_the_industry_tag_and_strips_the_market_suffix(self):
        from core.integrations.hithink.client import HithinkClient

        transport = RecordingTransport([
            FakeResponse(200, {
                'code': 0,
                'data': {
                    'item': [
                        {'thscode': '881121.TI', 'name': '半导体'},
                        {'thscode': '884096.TI', 'name': '光学元件'},
                    ],
                },
            }),
        ])

        with patch.dict('os.environ', self.settings, clear=False):
            indices = HithinkClient(transport=transport).list_industry_indices()

        self.assertEqual(transport.calls[0]['url'],
                         'https://hithink.test/api/a-share-index/catalog/ths-index-list')
        self.assertEqual(transport.calls[0]['params'], {'tag': 'industry'})
        self.assertEqual(
            [(index.thscode, index.industry_code, index.industry_name) for index in indices],
            [('881121.TI', '881121', '半导体'), ('884096.TI', '884096', '光学元件')],
        )

    def test_list_industry_constituents_returns_upstream_tickers(self):
        from core.integrations.hithink.client import HithinkClient

        transport = RecordingTransport([
            FakeResponse(200, {
                'code': 0,
                'data': {
                    'item': [
                        {'thscode': '600000.SH', 'ticker': '600000', 'name': '浦发银行'},
                        {'thscode': '920012.BJ', 'ticker': '920012', 'name': '北交所甲'},
                    ],
                },
            }),
        ])

        with patch.dict('os.environ', self.settings, clear=False):
            codes = HithinkClient(transport=transport).list_industry_constituents('881121.TI')

        self.assertEqual(codes, ('600000', '920012'))
        self.assertEqual(transport.calls[0]['url'],
                         'https://hithink.test/api/a-share-index/constituents/ths-stock-list')
        self.assertEqual(transport.calls[0]['params'], {'thscode': '881121.TI'})

    def test_list_industry_constituents_rejects_several_codes_in_one_call(self):
        from core.integrations.hithink.client import HithinkClient

        transport = RecordingTransport([])

        with patch.dict('os.environ', self.settings, clear=False):
            with self.assertRaises(ValueError):
                HithinkClient(transport=transport).list_industry_constituents(
                    '881121.TI,881122.TI'
                )

        self.assertEqual(transport.calls, [])

    def test_index_thscode_without_the_tonghuashun_suffix_is_rejected(self):
        from core.integrations.hithink.client import HithinkClient
        from core.integrations.hithink.contracts import HithinkPayloadError

        transport = RecordingTransport([
            FakeResponse(200, {
                'code': 0,
                'data': {'item': [{'thscode': '000300.SH', 'name': '沪深300'}]},
            }),
        ])

        with patch.dict('os.environ', self.settings, clear=False):
            with self.assertRaises(HithinkPayloadError):
                HithinkClient(transport=transport).list_industry_indices()
