from unittest.mock import patch

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
        'KAIPANLA_CHILD_INDUSTRY_ACTION': 'SonPlate_Info',
        'KAIPANLA_STOCK_LIST_ACTION': 'ZhiShuStockList_W8',
        'KAIPANLA_INDUSTRY_CONTROLLER': 'ZhiShuRanking',
        'KAIPANLA_INDUSTRY_PARENT_ORDER': '1',
        'KAIPANLA_INDUSTRY_PARENT_TYPE': '1',
        'KAIPANLA_INDUSTRY_PARENT_ZS_TYPE': '7',
        'KAIPANLA_INDUSTRY_CHILD_SHOW': '1',
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
            KaipanlaIndustryClient(transport=transport).list_parent_industries()

        self.assertEqual(
            transport.calls[0]['url'],
            settings['KAIPANLA_INDUSTRY_API_URL'],
        )

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
            industries = KaipanlaIndustryClient(transport=transport).list_parent_industries()

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

    def test_child_request_uses_configured_credentials_and_returns_actual_children(self):
        from core.integrations.kaipanla.client import KaipanlaIndustryClient

        transport = RecordingTransport([
            FakeResponse(200, {'errcode': '0', 'List': [
                ['801206', '光模块'],
            ]}),
        ])

        with patch.dict('os.environ', self.settings, clear=False):
            children = KaipanlaIndustryClient(transport=transport).list_child_industries('801660')

        self.assertEqual(children, (
            {'industry_code': '801206', 'industry_name': '光模块'},
        ))
        self.assertEqual(transport.calls[0]['data'], {
            'PhoneOSNew': '1',
            'DeviceID': 'device-id',
            'VerSion': '5.23.0.4',
            'apiv': 'w44',
            'UserID': 'user-id',
            'Token': 'token-value',
            'a': 'SonPlate_Info',
            'c': 'ZhiShuRanking',
            'IsShow': '1',
            'Date': '2026-09-08',
            'PlateID': '801660',
        })

    def test_industry_requests_allow_blank_credentials_and_omit_their_fields(self):
        from core.integrations.kaipanla.client import KaipanlaIndustryClient

        transport = RecordingTransport([
            FakeResponse(200, {'errcode': 0, 'list': [['801660', '通信']]}),
            FakeResponse(200, {'errcode': 0, 'List': [['801206', '光模块']]}),
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
            client.list_parent_industries()
            client.list_child_industries('801660')
            client.list_stock_codes('801206')

        self.assertEqual(len(transport.calls), 3)
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
                KaipanlaIndustryClient(transport=transport).list_parent_industries()

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
            FakeResponse(200, {'errcode': 0, 'List': []}),
        ])
        settings = {**self.settings, 'KAIPANLA_REQUEST_DELAY_SECONDS': '0.25'}

        with (
            patch.dict('os.environ', settings, clear=False),
            patch('core.integrations.kaipanla.client.sleep') as sleep,
        ):
            KaipanlaIndustryClient(transport=transport).list_child_industries('801660')

        sleep.assert_called_once_with(0.25)
