from datetime import datetime
from decimal import Decimal
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from core.models import DataVersion
from core.services.file_cache import FileCache
from core.services.cache_keys import build_cache_key
from kaipanla.models import KaipanlaSectorFundFlowSnapshot


class KaipanlaReadFallbackTests(TestCase):
    databases = {'default', 'kaipanla'}

    def setUp(self):
        self.trade_date = datetime(2026, 9, 8).date()
        KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').create(
            sector_code='A',
            sector_name='甲行业',
            trade_date=self.trade_date,
            snapshot_time=timezone.make_aware(datetime(2026, 9, 8, 15, 0)),
            main_net_inflow=Decimal('100000000'),
            source_batch_id='published-snapshot',
        )
        DataVersion.objects.create(
            dataset_key='kaipanla_sector_fund_flow',
            version='kaipanla-fallback-version',
            business_date=self.trade_date,
            status=DataVersion.Status.COMPLETE,
            expected_record_count=1,
            actual_record_count=1,
        )
        self.cache_directory = TemporaryDirectory()
        self.cache = FileCache(self.cache_directory.name, ttl_seconds=300, max_bytes=1_000_000)
        self.addCleanup(self.cache_directory.cleanup)

    @patch('kaipanla.services.read_path.default_file_cache')
    def test_corrupt_cache_falls_back_to_published_database_data(self, cache_factory):
        from kaipanla.services.read_path import read_intraday

        cache_factory.return_value = self.cache
        key = build_cache_key(
            'kaipanla',
            'sectors/intraday',
            {'date': '2026-09-08', 'inflow_top': 1, 'outflow_top': 1},
            'kaipanla-fallback-version',
        )
        path = self.cache.path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{not-json', encoding='utf-8')

        result = read_intraday(self.trade_date, inflow_top=1, outflow_top=1)

        self.assertEqual(result.source, 'database')
        self.assertEqual([item['code'] for item in result.data['series']], ['A'])

    @patch('kaipanla.services.read_path._can_attempt_repair', return_value=True)
    @patch('kaipanla.services.read_path._repair_current_snapshot', return_value=False)
    def test_missing_current_data_attempts_one_bounded_repair_then_reports_preparing(
        self, repair, can_repair
    ):
        from core.api.errors import ApiError, ErrorCode
        from kaipanla.services.read_path import read_intraday

        DataVersion.objects.all().delete()

        with self.assertRaises(ApiError) as raised:
            read_intraday(self.trade_date, inflow_top=1, outflow_top=1)

        self.assertEqual(raised.exception.code, ErrorCode.DATA_PREPARING)
        self.assertEqual(raised.exception.http_status, 202)
        can_repair.assert_called_once_with(self.trade_date)
        repair.assert_called_once_with(self.trade_date)

    @patch('kaipanla.services.read_path.KaipanlaSectorFundFlowFetcher')
    @patch('kaipanla.services.read_path.KaipanlaSectorFundFlowClient')
    @patch('kaipanla.services.read_path.flow_client_settings')
    def test_remote_repair_uses_one_page_no_retry_and_hard_timeout(
        self, flow_settings, client_class, fetcher_class
    ):
        from kaipanla.services.client import KaipanlaSectorFundFlowClientSettings
        from kaipanla.services.fetcher import KaipanlaSectorFundFlowFetchResult
        from kaipanla.services.parser import KaipanlaSectorFundFlowRow
        from kaipanla.services.read_path import _repair_current_snapshot

        DataVersion.objects.all().delete()
        flow_settings.return_value = KaipanlaSectorFundFlowClientSettings(
            endpoint='https://example.invalid', device_id='device', user_id='', token='',
            version='5.23.0.4', api_version='w44', phone_os_new='1', timeout_seconds=10,
            controller='ZhiShuRanking', action='RealRankingInfo', order='1', ranking_type='1',
            zs_type='7', page_size=80, request_delay_seconds=1.0,
        )
        fetcher_class.return_value.fetch.return_value = KaipanlaSectorFundFlowFetchResult(
            rows=(KaipanlaSectorFundFlowRow(
                sector_code='B', sector_name='乙行业', change_pct=None,
                main_net_inflow=Decimal('200000000'), main_buy=None, main_sell=None,
                large_order_net_inflow=None, volume_ratio=None, turnover_amount=None,
                float_market_cap=None, total_market_cap=None,
            ),),
            is_complete=True, expected_page_count=1, completed_page_count=1,
            failed_page_offsets=(), source_timestamp=int(
                timezone.make_aware(datetime(2026, 9, 8, 15, 0)).timestamp()
            ), source_trade_date='2026-09-08',
        )

        self.assertTrue(_repair_current_snapshot(self.trade_date))

        client_settings = client_class.call_args.kwargs['settings']
        self.assertEqual(client_settings.timeout_seconds, 5)
        self.assertEqual(client_settings.request_delay_seconds, 0.0)
        fetcher_class.assert_called_once_with(
            client=client_class.return_value,
            page_size=80,
            max_pages=1,
            max_retries=0,
            retry_delay_seconds=0.0,
        )
        self.assertEqual(
            DataVersion.objects.get(dataset_key='kaipanla_sector_fund_flow').status,
            DataVersion.Status.COMPLETE,
        )

    @patch('kaipanla.services.read_path.dataset_lock', side_effect=Exception('lock unavailable'))
    def test_repair_failure_never_publishes_a_version(self, lock):
        from kaipanla.services.read_path import _repair_current_snapshot

        DataVersion.objects.all().delete()

        self.assertFalse(_repair_current_snapshot(self.trade_date))
        self.assertFalse(DataVersion.objects.exists())
        lock.assert_called_once_with('kaipanla', 'kaipanla_sector_fund_flow')
