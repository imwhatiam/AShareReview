from decimal import Decimal
from unittest.mock import Mock, patch

from django.test import SimpleTestCase


class KaipanlaSectorFundFlowFetcherTests(SimpleTestCase):
    def test_fetches_required_pages_deduplicates_sectors_and_keeps_source_time(self):
        from kaipanla.services.fetcher import KaipanlaSectorFundFlowFetcher

        client = Mock()
        client.fetch_page.side_effect = (
            {
                'errcode': 0,
                'Count': 3,
                'Day': ['2026-09-08'],
                'Time': 1788852300,
                'list': [
                    ['BK001', '半导体', 0, '1.2', 0, '100', '20', '30', '10', '1.1', '50', 0, '4', '60'],
                    ['BK002', '通信设备', 0, '2.2', 0, '200', '40', '50', '10', '1.2', '60', 0, '5', '70'],
                ],
            },
            {
                'errcode': 0,
                'Count': 3,
                'Day': ['2026-09-08'],
                'Time': 1788852300,
                'list': [
                    ['BK001', '半导体更新', 0, '1.3', 0, '101', '21', '31', '10', '1.1', '51', 0, '4', '61'],
                ],
            },
        )

        result = KaipanlaSectorFundFlowFetcher(
            client=client,
            page_size=2,
            max_retries=0,
        ).fetch()

        self.assertTrue(result.is_complete)
        self.assertEqual(client.fetch_page.call_args_list[0].args, (0,))
        self.assertEqual(client.fetch_page.call_args_list[1].args, (2,))
        self.assertEqual(result.expected_page_count, 2)
        self.assertEqual(result.completed_page_count, 2)
        self.assertEqual(result.source_trade_date, '2026-09-08')
        self.assertEqual(result.source_timestamp, 1788852300)
        self.assertEqual([row.sector_code for row in result.rows], ['BK001', 'BK002'])
        self.assertEqual(result.rows[0].main_net_inflow, Decimal('21'))

    def test_retries_a_required_page_then_reports_failed_page_when_retries_are_exhausted(self):
        from kaipanla.services.client import KaipanlaUnavailableError
        from kaipanla.services.fetcher import KaipanlaSectorFundFlowFetcher

        client = Mock()
        client.fetch_page.side_effect = (
            {
                'errcode': 0,
                'Count': 3,
                'Day': ['2026-09-08'],
                'Time': 1788852300,
                'list': [
                    ['BK001', '半导体', 0, '1.2', 0, '100', '20', '30', '10', '1.1', '50', 0, '4', '60'],
                    ['BK002', '通信设备', 0, '2.2', 0, '200', '40', '50', '10', '1.2', '60', 0, '5', '70'],
                ],
            },
            KaipanlaUnavailableError('timeout'),
            KaipanlaUnavailableError('timeout'),
        )
        sleep = Mock()

        result = KaipanlaSectorFundFlowFetcher(
            client=client,
            page_size=2,
            max_retries=1,
            retry_delay_seconds=0.1,
            sleep=sleep,
        ).fetch()

        self.assertFalse(result.is_complete)
        self.assertEqual(result.expected_page_count, 2)
        self.assertEqual(result.completed_page_count, 1)
        self.assertEqual(result.failed_page_offsets, (2,))
        self.assertEqual(client.fetch_page.call_count, 3)
        sleep.assert_called_once_with(0.1)

    def test_rejects_an_empty_or_malformed_required_response_as_incomplete(self):
        from kaipanla.services.fetcher import KaipanlaSectorFundFlowFetcher

        client = Mock()
        client.fetch_page.return_value = {
            'errcode': 0,
            'Count': 'not-a-count',
            'list': [],
        }

        result = KaipanlaSectorFundFlowFetcher(client=client, page_size=80).fetch()

        self.assertFalse(result.is_complete)
        self.assertEqual(result.completed_page_count, 0)
        self.assertEqual(result.rows, ())

    def test_client_settings_allow_blank_credentials_and_omit_their_fields(self):
        from kaipanla.services.client import (
            KaipanlaSectorFundFlowClient,
            flow_client_settings,
        )

        class Response:
            status_code = 200
            text = r'{"errcode":0,"list":[["BK001","\u534a\u5bfc\u4f53"]]}'

        settings = {
            'KAIPANLA_API_URL': 'https://example.invalid',
            'KPL_DEVICE_ID': '',
            'KPL_USER_ID': '',
            'KPL_TOKEN': '',
            'KPL_VERSION': '5.23.0.4',
            'KPL_API_VERSION': 'w44',
            'KPL_PHONE_OS_NEW': '1',
            'KAIPANLA_TIMEOUT_SECONDS': '1',
            'KAIPANLA_FLOW_CONTROLLER': 'ZhiShuRanking',
            'KAIPANLA_FLOW_ACTION': 'RealRankingInfo',
            'KAIPANLA_FLOW_ORDER': '1',
            'KAIPANLA_FLOW_TYPE': '1',
            'KAIPANLA_FLOW_ZS_TYPE': '7',
            'KAIPANLA_FLOW_PAGE_SIZE': '80',
            'KAIPANLA_REQUEST_DELAY_SECONDS': '0',
        }
        transport = Mock()
        transport.post.return_value = Response()

        with patch.dict('os.environ', settings, clear=False):
            client = KaipanlaSectorFundFlowClient(
                settings=flow_client_settings(), transport=transport
            )
            client.fetch_page(0)

        posted = transport.post.call_args.kwargs['data']
        self.assertNotIn('DeviceID', posted)
        self.assertNotIn('UserID', posted)
        self.assertNotIn('Token', posted)

    def test_client_decodes_raw_unicode_escaped_payload_and_rejects_invalid_json(self):
        from kaipanla.services.client import (
            KaipanlaPayloadError,
            KaipanlaSectorFundFlowClient,
            KaipanlaSectorFundFlowClientSettings,
        )

        class Response:
            status_code = 200
            text = r'{"errcode":0,"list":[["BK001","\u534a\u5bfc\u4f53"]]}'

        transport = Mock()
        transport.post.return_value = Response()
        settings = KaipanlaSectorFundFlowClientSettings(
            endpoint='https://example.invalid',
            device_id='device-id',
            user_id='',
            token='',
            version='5.23.0.4',
            api_version='w44',
            phone_os_new='1',
            timeout_seconds=1,
            controller='ZhiShuRanking',
            action='RealRankingInfo',
            order='1',
            ranking_type='1',
            zs_type='7',
        )
        client = KaipanlaSectorFundFlowClient(settings=settings, transport=transport)

        payload = client.fetch_page(0)

        self.assertEqual(payload['list'][0][1], '半导体')
        posted = transport.post.call_args.kwargs['data']
        self.assertEqual(posted['st'], '80')
        self.assertEqual(posted['Index'], '0')
        self.assertEqual(posted['DeviceID'], 'device-id')
        self.assertNotIn('Token', posted)

        transport.post.return_value.text = '{invalid'
        with self.assertRaises(KaipanlaPayloadError):
            client.fetch_page(80)
