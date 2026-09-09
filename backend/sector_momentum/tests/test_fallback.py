from datetime import date
from decimal import Decimal
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import TestCase

from core.models import DataVersion
from core.services.cache_keys import build_cache_key
from core.services.contracts import (
    CompleteMarketSnapshot,
    MarketDataVersion,
    MarketPrice,
    ParentIndustry,
)
from core.services.file_cache import FileCache
from core.services.market_data import CompleteMarketDataUnavailable
from sector_momentum.models import SectorMomentumRanking, SectorMomentumResult
from sector_momentum.services.read_path import read_sector_momentum


class SectorMomentumFallbackTests(TestCase):
    databases = {'default', 'sector_momentum'}

    def setUp(self):
        self.trade_date = date(2026, 9, 8)
        self.result = SectorMomentumResult.objects.using('sector_momentum').create(
            business_date=self.trade_date,
            source_daily_price_version='daily-prices-v1',
            source_industry_version='industries-v1',
            total_market_turnover=Decimal('100'),
        )
        SectorMomentumRanking.objects.using('sector_momentum').create(
            result=self.result,
            metric=SectorMomentumRanking.Metric.ABOVE_5PCT,
            rank=1,
            industry_code='I1',
            industry_name='行业甲',
            stock_count=1,
            average_change_percent=Decimal('8'),
            industry_turnover=Decimal('100'),
            market_turnover_ratio=Decimal('1'),
            score=Decimal('8'),
            stocks=[],
        )
        self.cache_directory = TemporaryDirectory()
        self.cache = FileCache(self.cache_directory.name, ttl_seconds=300, max_bytes=1_000_000)
        self.addCleanup(self.cache_directory.cleanup)

    def _snapshot(self, count=1, version='daily-prices-v2'):
        return CompleteMarketSnapshot(
            data_version=MarketDataVersion(version=version, business_date=self.trade_date),
            prices=tuple(
                MarketPrice(
                    stock_code=f'600{number:03d}', thscode=f'600{number:03d}.SH',
                    stock_name=f'股票{number}', exchange='sse', trade_date=self.trade_date,
                    pre_close=None, open_price=None, high_price=None, low_price=None,
                    close_price=None, change_percent=Decimal('8'), volume=None,
                    turnover=Decimal('100'), has_valid_trade=True,
                )
                for number in range(1, count + 1)
            ),
            parent_industries=(ParentIndustry('I1', '行业甲', ('600001',)),),
        )

    @patch('sector_momentum.services.read_path.default_file_cache')
    def test_corrupted_cache_falls_back_to_database_data(self, cache_factory):
        cache_factory.return_value = self.cache
        key = build_cache_key(
            'sector_momentum', 'result', {'date': '2026-09-08'}, 'daily-prices-v1:industries-v1'
        )
        path = self.cache.path_for(key)
        path.parent.mkdir(parents=True)
        path.write_text('{not json', encoding='utf-8')

        result = read_sector_momentum(self.trade_date)

        self.assertEqual(result.source, 'database')
        self.assertEqual(result.data['rankings']['above_5pct'][0]['industry_code'], 'I1')

    @patch('sector_momentum.services.read_path.default_file_cache', return_value=None)
    @patch('sector_momentum.services.read_path.get_complete_market_snapshot')
    @patch.dict('os.environ', {'REMOTE_REPAIR_MAX_ROWS': '10'}, clear=False)
    def test_missing_result_rebuilds_from_small_local_public_snapshot(self, snapshot, _cache_factory):
        SectorMomentumRanking.objects.using('sector_momentum').all().delete()
        SectorMomentumResult.objects.using('sector_momentum').all().delete()
        DataVersion.objects.create(
            dataset_key='industry_snapshot', version='industries-v2',
            business_date=self.trade_date, status=DataVersion.Status.COMPLETE,
            expected_record_count=1, actual_record_count=1,
        )
        snapshot.return_value = self._snapshot()

        result = read_sector_momentum(self.trade_date)

        self.assertEqual(result.source, 'computed')
        self.assertEqual(result.data_version, 'daily-prices-v2:industries-v2')
        self.assertTrue(SectorMomentumResult.objects.using('sector_momentum').filter(
            source_daily_price_version='daily-prices-v2',
            source_industry_version='industries-v2',
        ).exists())

    @patch('core.services.sync_daily_prices.sync_stock_daily_prices')
    @patch('sector_momentum.services.read_path.get_complete_market_snapshot')
    def test_absent_public_data_never_starts_remote_full_market_sync(self, snapshot, sync):
        SectorMomentumRanking.objects.using('sector_momentum').all().delete()
        SectorMomentumResult.objects.using('sector_momentum').all().delete()
        snapshot.side_effect = CompleteMarketDataUnavailable('no complete public data')

        with self.assertRaises(CompleteMarketDataUnavailable):
            read_sector_momentum(self.trade_date)

        sync.assert_not_called()

    @patch('sector_momentum.services.read_path.get_complete_market_snapshot')
    @patch.dict('os.environ', {'REMOTE_REPAIR_MAX_ROWS': '1'}, clear=False)
    def test_large_local_rebuild_is_refused_so_web_requests_stay_bounded(self, snapshot):
        SectorMomentumRanking.objects.using('sector_momentum').all().delete()
        SectorMomentumResult.objects.using('sector_momentum').all().delete()
        DataVersion.objects.create(
            dataset_key='industry_snapshot', version='industries-v2',
            business_date=self.trade_date, status=DataVersion.Status.COMPLETE,
            expected_record_count=1, actual_record_count=1,
        )
        snapshot.return_value = self._snapshot(count=2)

        with self.assertRaises(CompleteMarketDataUnavailable):
            read_sector_momentum(self.trade_date)

    @patch('sector_momentum.services.read_path.get_complete_market_snapshot')
    @patch.dict('os.environ', {'REMOTE_REPAIR_MAX_ROWS': '10'}, clear=False)
    def test_stale_result_rebuilds_when_daily_or_industry_source_version_changes(self, snapshot):
        DataVersion.objects.create(
            dataset_key='stock_daily_prices', version='daily-prices-v2',
            business_date=self.trade_date, status=DataVersion.Status.COMPLETE,
            expected_record_count=1, actual_record_count=1,
        )
        DataVersion.objects.create(
            dataset_key='industry_snapshot', version='industries-v2',
            business_date=self.trade_date, status=DataVersion.Status.COMPLETE,
            expected_record_count=1, actual_record_count=1,
        )
        snapshot.return_value = self._snapshot()

        result = read_sector_momentum(self.trade_date)

        self.assertEqual(result.source, 'computed')
        self.assertFalse(result.stale)
        self.assertEqual(result.data_version, 'daily-prices-v2:industries-v2')
