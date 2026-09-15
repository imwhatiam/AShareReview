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

    def test_unparsable_rows_are_counted_instead_of_silently_dropped(self):
        """坏行必须留下数字：以前它被静默跳过，快照照样标 complete。

        板块可以整整一批消失，而运维唯一能看的 ``missing_record_count`` 恒为 0。
        现在每条坏行进 ``invalid_row_count``，上游 ``Count`` 进
        ``upstream_record_count``，两者之差就是"上游说有、我们没用上"的行数。
        """
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
                    # 长度不足 14：解析不出来
                    ['BK002', '通信设备', 0, '2.2'],
                    # 没有主力净流入：也被判为坏行
                    ['BK003', '证券', 0, '3.2', 0, '300', '-', '30', '10', '1.1', '50', 0, '4', '60'],
                ],
            },
        )

        result = KaipanlaSectorFundFlowFetcher(
            client=client,
            page_size=80,
            max_retries=0,
        ).fetch()

        self.assertTrue(result.is_complete)
        self.assertEqual([row.sector_code for row in result.rows], ['BK001'])
        self.assertEqual(result.invalid_row_count, 2)
        self.assertEqual(result.upstream_record_count, 3)

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
            sleep_fn=sleep,
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

    def test_an_injected_client_does_not_change_a_single_pagination_default(self):
        """注入 client 只换"用哪条传输"，不该换分页策略。

        以前三个参数会随 ``client`` 换源：``max_pages`` 变成写死的 ``100``（而
        `.env` 配的是 20）、``retry_delay_seconds`` 变成写死的 ``0.0``，而
        ``page_size`` 干脆没有兜底（``None.page_size`` 直接 AttributeError）。
        四个值现在都从同一份配置取默认值，所以下面的显式字面量必须一个个对上。
        """
        from kaipanla.services.client import KaipanlaSectorFundFlowClientSettings
        from kaipanla.services.fetcher import KaipanlaSectorFundFlowFetcher

        client_settings = KaipanlaSectorFundFlowClientSettings(
            endpoint='https://example.invalid',
            device_id='',
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
            zs_type='4',
            page_size=17,
            request_delay_seconds=0.25,
        )

        with patch.dict(
            'os.environ',
            {'KAIPANLA_MAX_RETRIES': '3', 'KAIPANLA_FLOW_MAX_PAGES': '7'},
            clear=False,
        ), patch(
            'kaipanla.services.fetcher.flow_client_settings',
            return_value=client_settings,
        ):
            fetcher = KaipanlaSectorFundFlowFetcher(client=Mock())

        self.assertEqual(fetcher.page_size, 17)
        self.assertEqual(fetcher.max_retries, 3)
        self.assertEqual(fetcher.retry_delay_seconds, 0.25)
        self.assertEqual(fetcher.max_pages, 7)

    def test_explicit_keywords_still_win_over_the_configured_defaults(self):
        """显式传参必须压过配置：单次受控采集（例如 0 重试 + 有限页数）靠它做到。"""
        from kaipanla.services.fetcher import KaipanlaSectorFundFlowFetcher

        with patch.dict(
            'os.environ',
            {'KAIPANLA_MAX_RETRIES': '3', 'KAIPANLA_FLOW_MAX_PAGES': '20'},
            clear=False,
        ):
            fetcher = KaipanlaSectorFundFlowFetcher(
                client=Mock(),
                page_size=80,
                max_pages=3,
                max_retries=0,
                retry_delay_seconds=0.0,
            )

        self.assertEqual(fetcher.page_size, 80)
        self.assertEqual(fetcher.max_pages, 3)
        self.assertEqual(fetcher.max_retries, 0)
        self.assertEqual(fetcher.retry_delay_seconds, 0.0)

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


class KaipanlaClientUpstreamErrorCodeTests(SimpleTestCase):
    """资金流链路的失败必须能在日志里被认出来。

    2026-09-15 之前，``kaipanla/services/client.py`` 与
    ``core/integrations/kaipanla/client.py`` 各自声明了**同名但不同对象**的
    ``KaipanlaUnavailableError`` / ``KaipanlaRateLimitError``，而
    ``core.api.errors.upstream_error_code`` 只 isinstance 后者那一套。于是资金流
    链路无论是被 429 限流还是上游直接挂掉，``data_command_failed`` /
    ``upstream_failed`` 里的 ``error_code`` **恒为空**，运维分不出这两种情况。
    现在两处共用 ``core.integrations.kaipanla.contracts`` 里的一套名字。
    """

    def _settings(self, **overrides):
        from kaipanla.services.client import KaipanlaSectorFundFlowClientSettings

        values = {
            'endpoint': 'https://example.invalid',
            'device_id': '', 'user_id': '', 'token': '',
            'version': '5.23.0.4', 'api_version': 'w44', 'phone_os_new': '1',
            'timeout_seconds': 1,
            'controller': 'ZhiShuRanking', 'action': 'RealRankingInfo',
            'order': '1', 'ranking_type': '1', 'zs_type': '4',
        }
        values.update(overrides)
        return KaipanlaSectorFundFlowClientSettings(**values)

    def test_the_two_adapters_share_one_set_of_exception_classes(self):
        from core.integrations.kaipanla import client as industry_client
        from kaipanla.services import client as flow_client

        self.assertIs(flow_client.KaipanlaUnavailableError, industry_client.KaipanlaUnavailableError)
        self.assertIs(flow_client.KaipanlaRateLimitError, industry_client.KaipanlaRateLimitError)
        self.assertIs(flow_client.KaipanlaPayloadError, industry_client.KaipanlaPayloadError)

    def test_flow_failures_map_to_the_same_error_codes_as_industry_failures(self):
        from core.api.errors import upstream_error_code_value
        from kaipanla.services.client import KaipanlaRateLimitError, KaipanlaPayloadError, KaipanlaUnavailableError

        self.assertEqual(upstream_error_code_value(KaipanlaRateLimitError('x')), 'UPSTREAM_RATE_LIMITED')
        self.assertEqual(upstream_error_code_value(KaipanlaUnavailableError('x')), 'UPSTREAM_UNAVAILABLE')
        # payload/契约错误不是传输失败，故意留空而不是错标成"上游挂了"。
        self.assertIsNone(upstream_error_code_value(KaipanlaPayloadError('x')))

    def test_throttling_and_transport_failures_log_distinct_error_codes(self):
        import requests

        from core.integrations.kaipanla.contracts import KaipanlaRateLimitError, KaipanlaUnavailableError
        from kaipanla.services.client import KaipanlaSectorFundFlowClient

        class Response:
            status_code = 429
            text = ''

        transport = Mock()
        transport.post.return_value = Response()

        with patch('kaipanla.services.client.log_event') as log_event:
            with self.assertRaises(KaipanlaRateLimitError):
                KaipanlaSectorFundFlowClient(settings=self._settings(), transport=transport).fetch_page(0)

        self.assertEqual(log_event.call_args.kwargs['error_code'], 'UPSTREAM_RATE_LIMITED')
        self.assertEqual(log_event.call_args.kwargs['status'], 429)

        transport.post.side_effect = requests.ConnectionError('boom')
        with patch('kaipanla.services.client.log_event') as log_event:
            with self.assertRaises(KaipanlaUnavailableError) as caught:
                KaipanlaSectorFundFlowClient(settings=self._settings(), transport=transport).fetch_page(0)

        self.assertEqual(log_event.call_args.kwargs['error_code'], 'UPSTREAM_UNAVAILABLE')
        # 网络那一支不再把 error_code 写死：它现在同样由异常类型推出来。
        self.assertNotIsInstance(caught.exception, KaipanlaRateLimitError)
