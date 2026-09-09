from datetime import datetime
from decimal import Decimal
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from core.models import DataVersion, ModuleRunStatus
from core.services.cache_keys import build_cache_key
from core.services.file_cache import FileCache
from eastmoney.models import EastmoneySectorFundFlowSnapshot


class EastmoneyReadFallbackTests(TestCase):
    databases = {'default', 'eastmoney'}

    def setUp(self):
        self.trade_date = datetime(2026, 9, 8).date()
        EastmoneySectorFundFlowSnapshot.objects.using('eastmoney').create(
            sector_code='A',
            sector_name='甲行业',
            trade_date=self.trade_date,
            snapshot_time=timezone.make_aware(datetime(2026, 9, 8, 15, 0)),
            main_net_inflow=Decimal('100000000'),
            source_batch_id='published-snapshot',
        )
        DataVersion.objects.create(
            dataset_key='eastmoney_sector_fund_flow',
            version='eastmoney-fallback-version',
            business_date=self.trade_date,
            status=DataVersion.Status.COMPLETE,
            expected_record_count=1,
            actual_record_count=1,
        )
        self.cache_directory = TemporaryDirectory()
        self.cache = FileCache(self.cache_directory.name, ttl_seconds=300, max_bytes=1_000_000)
        self.addCleanup(self.cache_directory.cleanup)

    @patch('eastmoney.services.read_path.default_file_cache')
    def test_corrupt_cache_falls_back_to_published_database_data(self, cache_factory):
        from eastmoney.services.read_path import read_intraday

        cache_factory.return_value = self.cache
        key = build_cache_key(
            'eastmoney',
            'sectors/intraday',
            {'date': '2026-09-08', 'inflow_top': 1, 'outflow_top': 1},
            'eastmoney-fallback-version',
        )
        path = self.cache.path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{not-json', encoding='utf-8')

        result = read_intraday(self.trade_date, inflow_top=1, outflow_top=1)

        self.assertEqual(result.source, 'database')
        self.assertEqual([item['code'] for item in result.data['series']], ['A'])

    def test_failed_collection_serves_old_data_as_stale_without_remote_repair(self):
        from eastmoney.services.read_path import read_intraday

        ModuleRunStatus.objects.create(
            module_id='eastmoney',
            dataset_key='eastmoney_sector_fund_flow',
            status=ModuleRunStatus.Status.FAILED,
            completeness=DataVersion.Status.FAILED,
            business_date=datetime(2026, 9, 9).date(),
            source_data_version='eastmoney-fallback-version',
            serving_stale=True,
            error_summary='HTTP 403 blocked by upstream.',
        )

        result = read_intraday(None, inflow_top=1, outflow_top=0)

        self.assertEqual(result.business_date, self.trade_date)
        self.assertTrue(result.stale)
        self.assertIn('东方财富上游数据暂不可用，正在展示最近可用数据。', result.warnings)
