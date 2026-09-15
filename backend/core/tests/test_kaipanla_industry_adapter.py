from datetime import datetime
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from django.utils import timezone


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

    def post(self, url, *, data, headers, timeout):
        self.calls.append({
            'url': url,
            'data': data,
            'headers': headers,
            'timeout': timeout,
        })
        return self.responses.pop(0)


class KaipanlaIndustryClientTests(SimpleTestCase):
    settings = {
        'KAIPANLA_API_URL': 'https://example.test/w1/api/index.php',
        'KAIPANLA_INDUSTRY_API_URL': 'https://history.example.test/w1/api/index.php',
        'KPL_DEVICE_ID': 'device-id',
        'KPL_USER_ID': 'user-id',
        'KPL_TOKEN': 'token-value',
        'KPL_VERSION': '5.23.0.4',
        'KPL_API_VERSION': 'w44',
        'KPL_PHONE_OS_NEW': '1',
        'KAIPANLA_TIMEOUT_SECONDS': '10',
        'KAIPANLA_REQUEST_DELAY_SECONDS': '0',
        'KAIPANLA_MAX_RETRIES': '0',
        'KAIPANLA_INDUSTRY_PARENT_PAGE_SIZE': '2',
        'KAIPANLA_INDUSTRY_STOCK_PAGE_SIZE': '2',
        'KAIPANLA_PARENT_INDUSTRY_ACTION': 'RealRankingInfo',
        'KAIPANLA_STOCK_LIST_ACTION': 'ZhiShuStockList_W8',
        'KAIPANLA_INDUSTRY_CONTROLLER': 'ZhiShuRanking',
        'KAIPANLA_INDUSTRY_PARENT_ORDER': '1',
        'KAIPANLA_INDUSTRY_PARENT_TYPE': '1',
        'KAIPANLA_INDUSTRY_PARENT_ZS_TYPE': '7',
        'KAIPANLA_INDUSTRY_STOCK_ORDER': '1',
        'KAIPANLA_INDUSTRY_STOCK_TSZB': '0',
        'KAIPANLA_INDUSTRY_STOCK_OLD': '1',
        'KAIPANLA_INDUSTRY_STOCK_IS_ZZ': '0',
        'KAIPANLA_INDUSTRY_STOCK_TYPE': '6',
        'KAIPANLA_INDUSTRY_STOCK_IS_KZZ_TYPE': '0',
        'KAIPANLA_INDUSTRY_DATE': '2026-09-08',
    }

    def test_industry_requests_use_the_independently_configured_history_endpoint(self):
        from core.integrations.kaipanla.client import KaipanlaIndustryClient

        transport = RecordingTransport([
            FakeResponse(200, {'errcode': 0, 'list': [['801660', '通信']]}),
        ])
        settings = {
            **self.settings,
            'KAIPANLA_INDUSTRY_API_URL': 'https://history.example.test/w1/api/index.php',
        }

        with patch.dict('os.environ', settings, clear=False):
            KaipanlaIndustryClient(transport=transport).list_industries()

        self.assertEqual(
            transport.calls[0]['url'],
            settings['KAIPANLA_INDUSTRY_API_URL'],
        )

    def test_industry_and_flow_adapters_send_the_same_configured_headers(self):
        """两个开盘啦端点必须报同一个客户端身份，且都听 ``KAIPANLA_USER_AGENT``。

        此前行业适配器把 UA **硬编码**在请求里、资金流适配器才读配置，于是改
        ``KAIPANLA_USER_AGENT`` 只会悄悄影响两个端点中的一个。
        """
        from core.integrations.kaipanla.client import KaipanlaIndustryClient
        from core.integrations.kaipanla.contracts import DEFAULT_USER_AGENT, request_headers

        transport = RecordingTransport([
            FakeResponse(200, {'errcode': 0, 'list': []}),
        ])
        settings = {**self.settings, 'KAIPANLA_USER_AGENT': 'MarketReview/1.0'}

        with patch.dict('os.environ', settings, clear=False):
            expected = request_headers()
            KaipanlaIndustryClient(transport=transport).list_industries()

        self.assertEqual(expected['User-Agent'], 'MarketReview/1.0')
        self.assertEqual(transport.calls[0]['headers'], expected)
        self.assertEqual(expected['Content-Type'], 'application/x-www-form-urlencoded; charset=UTF-8')
        self.assertEqual(expected['Accept-Encoding'], 'gzip')
        self.assertEqual(expected['Connection'], 'Keep-Alive')

        # 未配置时两个端点退回同一个兜底 UA，而不是各自持有不同的字面量。
        with patch.dict('os.environ', {**self.settings, 'KAIPANLA_USER_AGENT': ''}, clear=False):
            self.assertEqual(request_headers()['User-Agent'], DEFAULT_USER_AGENT)

    def test_parent_industry_request_uses_configured_real_ranking_contract(self):
        from core.integrations.kaipanla.client import KaipanlaIndustryClient

        transport = RecordingTransport([
            FakeResponse(200, {'errcode': 0, 'list': [
                ['801660', '通信'],
                ['801670', '传媒'],
            ]}),
            FakeResponse(200, {'errcode': 0, 'list': []}),
        ])

        with patch.dict('os.environ', self.settings, clear=False):
            industries = KaipanlaIndustryClient(transport=transport).list_industries()

        self.assertEqual(industries, (
            {'industry_code': '801660', 'industry_name': '通信'},
            {'industry_code': '801670', 'industry_name': '传媒'},
        ))
        self.assertEqual(transport.calls[0]['url'], self.settings['KAIPANLA_INDUSTRY_API_URL'])
        self.assertEqual(transport.calls[0]['data'], {
            'PhoneOSNew': '1',
            'DeviceID': 'device-id',
            'VerSion': '5.23.0.4',
            'apiv': 'w44',
            'UserID': 'user-id',
            'Token': 'token-value',
            'Order': '1',
            'a': 'RealRankingInfo',
            'st': '2',
            'c': 'ZhiShuRanking',
            'Index': '0',
            'Date': '2026-09-08',
            'Type': '1',
            'ZSType': '7',
        })
        self.assertEqual(transport.calls[1]['data']['Index'], '2')

    def test_industry_requests_allow_blank_credentials_and_omit_their_fields(self):
        from core.integrations.kaipanla.client import KaipanlaIndustryClient

        transport = RecordingTransport([
            FakeResponse(200, {'errcode': 0, 'list': [['801660', '通信']]}),
            FakeResponse(200, {'errcode': 0, 'list': [['000001', '平安银行']]}),
        ])
        settings = {
            **self.settings,
            'KPL_DEVICE_ID': '',
            'KPL_USER_ID': '',
            'KPL_TOKEN': '',
        }

        with patch.dict('os.environ', settings, clear=False):
            client = KaipanlaIndustryClient(transport=transport)
            client.list_industries()
            client.list_stock_codes('801660')

        self.assertEqual(len(transport.calls), 2)
        for call in transport.calls:
            self.assertNotIn('DeviceID', call['data'])
            self.assertNotIn('UserID', call['data'])
            self.assertNotIn('Token', call['data'])

    def test_stock_list_paginates_and_deduplicates_codes(self):
        from core.integrations.kaipanla.client import KaipanlaIndustryClient

        transport = RecordingTransport([
            FakeResponse(200, {'errcode': 0, 'list': [
                ['000001', '平安银行'],
                ['000002', '万科A'],
            ]}),
            FakeResponse(200, {'errcode': 0, 'list': [
                ['000002', '万科A'],
                ['000003', 'PT金田A'],
            ]}),
            FakeResponse(200, {'errcode': 0, 'list': []}),
        ])

        with patch.dict('os.environ', self.settings, clear=False):
            stock_codes = KaipanlaIndustryClient(transport=transport).list_stock_codes('801206')

        self.assertEqual(stock_codes, ('000001', '000002', '000003'))
        self.assertEqual([call['data']['Index'] for call in transport.calls], ['0', '2', '4'])
        self.assertEqual(transport.calls[0]['data']['a'], 'ZhiShuStockList_W8')
        self.assertEqual(transport.calls[0]['data']['Type'], '6')

    def test_nonzero_business_error_is_not_treated_as_empty_data(self):
        from core.integrations.kaipanla.client import (
            KaipanlaIndustryClient,
            KaipanlaUnavailableError,
        )

        transport = RecordingTransport([
            FakeResponse(200, {'errcode': 1001, 'errmsg': 'rejected'}),
        ])

        with patch.dict('os.environ', self.settings, clear=False):
            with self.assertRaises(KaipanlaUnavailableError):
                KaipanlaIndustryClient(transport=transport).list_industries()

    def test_rejection_message_carries_the_upstream_error_code_and_reason(self):
        """只留 "request was rejected" 会让 1020 这类参数错误无从下手。"""
        from core.integrations.kaipanla.client import (
            KaipanlaIndustryClient,
            KaipanlaUnavailableError,
        )

        transport = RecordingTransport([
            FakeResponse(200, {'errcode': 1020, 'errmsg': '参数出错'}),
        ])

        with patch.dict('os.environ', self.settings, clear=False):
            with self.assertRaises(KaipanlaUnavailableError) as caught:
                KaipanlaIndustryClient(transport=transport).list_industries()

        self.assertIn('errcode=1020', str(caught.exception))
        self.assertIn('参数出错', str(caught.exception))

    def test_malformed_stock_code_is_rejected_instead_of_persisted(self):
        from core.integrations.kaipanla.client import (
            KaipanlaIndustryClient,
            KaipanlaPayloadError,
        )

        transport = RecordingTransport([
            FakeResponse(200, {'errcode': 0, 'list': [
                ['not-a-stock', '异常数据'],
            ]}),
        ])

        with patch.dict('os.environ', self.settings, clear=False):
            with self.assertRaises(KaipanlaPayloadError):
                KaipanlaIndustryClient(transport=transport).list_stock_codes('801206')

    def test_configured_request_delay_is_applied_before_each_upstream_call(self):
        from core.integrations.kaipanla.client import KaipanlaIndustryClient

        transport = RecordingTransport([
            FakeResponse(200, {'errcode': 0, 'list': []}),
        ])
        settings = {**self.settings, 'KAIPANLA_REQUEST_DELAY_SECONDS': '0.25'}

        with (
            patch.dict('os.environ', settings, clear=False),
            patch('core.integrations.kaipanla.client.sleep') as sleep,
        ):
            KaipanlaIndustryClient(transport=transport).list_industries()

        sleep.assert_called_once_with(0.25)


class KaipanlaIndustryRequestDateTests(TestCase):
    """行业历史接口只服务交易日，Date 默认值不能是本地日期。

    回归：2026-09-12（周六）运行 `sync_kaipanla_industry_snapshot` 时，命令把
    周六当作 Date 发出去，上游回 `errcode 1020 参数出错`，命令以晦涩的
    "Kaipanla request was rejected." 失败。
    """

    settings = {**KaipanlaIndustryClientTests.settings, 'KAIPANLA_INDUSTRY_DATE': ''}

    def _request_date_at(self, *parts):
        from core.integrations.kaipanla.client import KaipanlaIndustryClient

        transport = RecordingTransport([
            FakeResponse(200, {'errcode': 0, 'list': [['801660', '通信']]}),
        ])
        moment = timezone.make_aware(datetime(*parts))
        with (
            patch.dict('os.environ', self.settings, clear=False),
            patch('django.utils.timezone.now', return_value=moment),
        ):
            KaipanlaIndustryClient(transport=transport).list_industries()
        return transport.calls[0]['data']['Date']

    def test_trading_day_query_uses_that_same_day(self):
        self.assertEqual(self._request_date_at(2026, 9, 10, 10, 0), '2026-09-10')

    def test_weekend_query_falls_back_to_the_latest_trading_day(self):
        self.assertEqual(self._request_date_at(2026, 9, 12, 9, 30), '2026-09-11')

    def test_configured_date_still_overrides_the_fallback(self):
        from core.integrations.kaipanla.client import KaipanlaIndustryClient

        transport = RecordingTransport([
            FakeResponse(200, {'errcode': 0, 'list': [['801660', '通信']]}),
        ])
        settings = {**self.settings, 'KAIPANLA_INDUSTRY_DATE': '2026-09-09'}

        with (
            patch.dict('os.environ', settings, clear=False),
            patch(
                'django.utils.timezone.now',
                return_value=timezone.make_aware(datetime(2026, 9, 12, 9, 30)),
            ),
        ):
            KaipanlaIndustryClient(transport=transport).list_industries()

        self.assertEqual(transport.calls[0]['data']['Date'], '2026-09-09')
