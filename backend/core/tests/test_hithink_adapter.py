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

    def test_list_trading_days_parses_upstream_compact_dates(self):
        from core.integrations.hithink.client import HithinkClient

        transport = RecordingTransport([
            FakeResponse(200, {
                'code': 0,
                'data': {
                    'item': [
                        {'date_ms': 1788796800000, 'date': '20260908'},
                        {'date_ms': 1788883200000, 'date': '20260909'},
                    ],
                },
            }),
        ])

        with patch.dict('os.environ', self.settings, clear=False):
            trading_days = HithinkClient(transport=transport).list_trading_days()

        self.assertEqual(trading_days, (date(2026, 9, 8), date(2026, 9, 9)))
        self.assertEqual(transport.calls[0]['params'], {})

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
                ])).list_trading_days()
            with self.assertRaises(HithinkAuthenticationError):
                HithinkClient(transport=RecordingTransport([
                    FakeResponse(200, {'code': 2003, 'data': None}),
                ])).list_trading_days()

    def test_transport_timeout_is_mapped_to_upstream_unavailable(self):
        from core.integrations.hithink.client import HithinkClient
        from core.integrations.hithink.contracts import HithinkUnavailableError

        transport = RecordingTransport([requests.Timeout('timed out')])

        with patch.dict('os.environ', self.settings, clear=False):
            with self.assertRaises(HithinkUnavailableError):
                HithinkClient(transport=transport).list_trading_days()
