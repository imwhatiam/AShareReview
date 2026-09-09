from dataclasses import replace
from unittest.mock import Mock

from django.test import SimpleTestCase

from eastmoney.services.client import (
    EastmoneySectorFundFlowClient,
    EastmoneySectorFundFlowClientSettings,
    EastmoneyUnavailableError,
)
from eastmoney.services.fetcher import EastmoneySectorFundFlowFetcher
from eastmoney.services.parser import extract_ranking_rows, parse_sector_row


class _FakeResponse:
    def __init__(self, *, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _FakeTransport:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def get(self, endpoint, **kwargs):
        self.calls.append((endpoint, kwargs))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


class EastmoneyClientTests(SimpleTestCase):
    def test_client_uses_configured_endpoint_and_direction_specific_parameters(self):
        settings = EastmoneySectorFundFlowClientSettings(
            endpoint='https://example.test/clist',
            timeout_seconds=7,
            request_delay_seconds=0,
            ut='test-ut',
            page_size=50,
            fields='f12,f14,f62',
            inflow_fs='inflow-filter',
            outflow_fs='outflow-filter',
            inflow_order='1',
            outflow_order='0',
            np='1',
            fltt='2',
            invt='2',
            fid='f62',
            stat='1',
            page_number='1',
        )
        transport = _FakeTransport([_FakeResponse(payload={'data': {'diff': []}})])
        client = EastmoneySectorFundFlowClient(settings=settings, transport=transport)

        client.fetch_ranking('inflow')

        self.assertEqual(transport.calls, [
            (
                'https://example.test/clist',
                {
                    'params': {
                        'po': '1', 'np': '1', 'fltt': '2', 'invt': '2',
                        'ut': 'test-ut', 'fid': 'f62', 'fs': 'inflow-filter',
                        'stat': '1', 'fields': 'f12,f14,f62', 'pn': '1', 'pz': 50,
                    },
                    'timeout': 7,
                },
            )
        ])

    def test_client_treats_upstream_block_as_unavailable(self):
        settings = replace(_client_settings(), request_delay_seconds=0)
        client = EastmoneySectorFundFlowClient(
            settings=settings,
            transport=_FakeTransport([_FakeResponse(status_code=403, payload={})]),
        )

        with self.assertRaisesRegex(EastmoneyUnavailableError, 'HTTP 403'):
            client.fetch_ranking('outflow')


class EastmoneyParserTests(SimpleTestCase):
    def test_parser_accepts_dictionary_or_list_diff_and_discards_invalid_rows(self):
        payload = {'data': {'diff': {'one': {'f12': 'BK001', 'f62': '123.45'}}}}
        self.assertEqual(extract_ranking_rows(payload), [{'f12': 'BK001', 'f62': '123.45'}])
        self.assertEqual(
            parse_sector_row({'f12': 'BK001', 'f14': '半导体', 'f62': '123.45', 'f124': 1}),
            {
                'sector_code': 'BK001',
                'sector_name': '半导体',
                'latest_index': None,
                'change_pct': None,
                'main_net_inflow': '123.45',
                'main_net_inflow_ratio': None,
                'super_large_net_inflow': None,
                'large_net_inflow': None,
                'medium_net_inflow': None,
                'small_net_inflow': None,
            },
        )
        self.assertIsNone(parse_sector_row({'f12': 'BK001'}))


class EastmoneyFetcherTests(SimpleTestCase):
    def test_fetcher_keeps_successful_inflow_when_outflow_is_blocked(self):
        client = Mock()
        client.fetch_ranking.side_effect = [
            {'data': {'diff': [{'f12': 'BK001', 'f14': '半导体', 'f62': '12.5'}]}},
            EastmoneyUnavailableError('HTTP 403 blocked by upstream.'),
        ]
        fetcher = EastmoneySectorFundFlowFetcher(
            client=client,
            max_retries=0,
            retry_delay_seconds=0,
            ranking_interval_seconds=0,
        )

        result = fetcher.fetch()

        self.assertTrue(result.inflow.succeeded)
        self.assertFalse(result.outflow.succeeded)
        self.assertEqual(result.inflow.record_count, 1)
        self.assertEqual(result.outflow.record_count, 0)
        self.assertIn('HTTP 403', result.outflow.error_summary)
        self.assertEqual([row['sector_code'] for row in result.rows], ['BK001'])
        self.assertEqual(client.fetch_ranking.call_args_list[0].args, ('inflow',))
        self.assertEqual(client.fetch_ranking.call_args_list[1].args, ('outflow',))

    def test_fetcher_returns_no_publishable_rows_when_both_rankings_fail(self):
        client = Mock()
        client.fetch_ranking.side_effect = [
            EastmoneyUnavailableError('HTTP 403 blocked by upstream.'),
            EastmoneyUnavailableError('HTTP 403 blocked by upstream.'),
        ]
        fetcher = EastmoneySectorFundFlowFetcher(
            client=client,
            max_retries=0,
            retry_delay_seconds=0,
            ranking_interval_seconds=0,
        )

        result = fetcher.fetch()

        self.assertFalse(result.inflow.succeeded)
        self.assertFalse(result.outflow.succeeded)
        self.assertEqual(result.rows, ())
        self.assertFalse(result.has_publishable_rows)

    def test_fetcher_retries_a_failed_ranking_only_up_to_configured_limit(self):
        client = Mock()
        client.fetch_ranking.side_effect = [
            EastmoneyUnavailableError('timeout'),
            {'data': {'diff': [{'f12': 'BK002', 'f14': '通信设备', 'f62': '10'}]}},
            {'data': {'diff': [{'f12': 'BK003', 'f14': '计算机', 'f62': '-10'}]}},
        ]
        sleep = Mock()
        fetcher = EastmoneySectorFundFlowFetcher(
            client=client,
            max_retries=1,
            retry_delay_seconds=2,
            ranking_interval_seconds=3,
            sleep_fn=sleep,
        )

        result = fetcher.fetch()

        self.assertTrue(result.inflow.succeeded)
        self.assertTrue(result.outflow.succeeded)
        self.assertEqual(client.fetch_ranking.call_count, 3)
        self.assertEqual(sleep.call_args_list, [((2,),), ((3,),)])


def _client_settings():
    return EastmoneySectorFundFlowClientSettings(
        endpoint='https://example.test/clist',
        timeout_seconds=7,
        request_delay_seconds=0,
        ut='test-ut',
        page_size=50,
        fields='f12,f14,f62',
        inflow_fs='inflow-filter',
        outflow_fs='outflow-filter',
        inflow_order='1',
        outflow_order='0',
        np='1',
        fltt='2',
        invt='2',
        fid='f62',
        stat='1',
        page_number='1',
    )
