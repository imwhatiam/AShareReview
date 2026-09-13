from datetime import date
from decimal import Decimal
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import TestCase

from core.api.errors import ApiError, ErrorCode
from core.models import DataVersion
from core.services.cache_keys import build_cache_key
from core.services.contracts import (
    CompleteMarketSnapshot,
    MarketDataVersion,
    MarketPrice,
    Industry,
)
from core.services.file_cache import FileCache
from core.services.locking import DatasetLocked
from core.services.market_data import CompleteMarketDataUnavailable
from sector_momentum.models import SectorMomentumRanking, SectorMomentumResult
from sector_momentum.services.read_path import read_sector_momentum
from sector_momentum.services.source_versions import CompleteIndustrySnapshotUnavailable


class SectorMomentumFallbackTests(TestCase):
    databases = {'default', 'sector_momentum'}

    def setUp(self):
        self.trade_date = date(2026, 9, 8)
        self.next_trade_date = date(2026, 9, 9)
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
        # 默认文件缓存会落到磁盘并在多次运行之间复用，会让 source 断言变得不确定；
        # 这里统一关掉，只有显式验证缓存行为的用例再用装饰器打开。
        cache_patch = patch(
            'sector_momentum.services.read_path.default_file_cache', return_value=None
        )
        cache_patch.start()
        self.addCleanup(cache_patch.stop)

    def _snapshot(self, count=1, version='daily-prices-v2', trade_date=None):
        day = trade_date or self.trade_date
        return CompleteMarketSnapshot(
            data_version=MarketDataVersion(version=version, business_date=day),
            prices=tuple(
                MarketPrice(
                    stock_code=f'600{number:03d}', thscode=f'600{number:03d}.SH',
                    stock_name=f'股票{number}', exchange='sse', trade_date=day,
                    pre_close=None, open_price=None, high_price=None, low_price=None,
                    close_price=None, change_percent=Decimal('8'), volume=None,
                    turnover=Decimal('100'), has_valid_trade=True,
                )
                for number in range(1, count + 1)
            ),
            industries=(Industry('I1', '行业甲', ('600001',)),),
        )

    def _complete_version(self, dataset_key, version, business_date=None):
        return DataVersion.objects.create(
            dataset_key=dataset_key,
            version=version,
            business_date=business_date or self.trade_date,
            status=DataVersion.Status.COMPLETE,
            expected_record_count=1,
            actual_record_count=1,
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

    @patch('sector_momentum.services.read_path.get_complete_industry_snapshot_version')
    @patch('sector_momentum.services.read_path.get_complete_market_snapshot')
    def test_missing_result_is_generated_from_local_public_snapshot(self, snapshot, industry):
        SectorMomentumRanking.objects.using('sector_momentum').all().delete()
        SectorMomentumResult.objects.using('sector_momentum').all().delete()
        snapshot.return_value = self._snapshot()
        industry.return_value = 'industries-v2'

        result = read_sector_momentum(self.trade_date)

        self.assertEqual(result.source, 'computed')
        self.assertFalse(result.stale)
        self.assertEqual(result.data_version, 'daily-prices-v2:industries-v2')
        self.assertTrue(SectorMomentumResult.objects.using('sector_momentum').filter(
            source_daily_price_version='daily-prices-v2',
            source_industry_version='industries-v2',
        ).exists())

    @patch('sector_momentum.services.read_path.get_complete_industry_snapshot_version')
    @patch('sector_momentum.services.read_path.get_complete_market_snapshot')
    def test_large_snapshot_is_generated_without_a_row_budget(self, snapshot, industry):
        """The local generation path is a computation, not a bounded remote repair."""
        SectorMomentumRanking.objects.using('sector_momentum').all().delete()
        SectorMomentumResult.objects.using('sector_momentum').all().delete()
        snapshot.return_value = self._snapshot(count=2500)
        industry.return_value = 'industries-v2'

        result = read_sector_momentum(self.trade_date)

        self.assertEqual(result.source, 'computed')
        self.assertEqual(result.data['total_market_turnover'], Decimal('100') * 2500)

    @patch('sector_momentum.services.read_path.get_complete_market_snapshot')
    def test_explicit_date_without_generatable_data_stays_unavailable(self, snapshot):
        """An explicit date must never silently answer with another day's result."""
        snapshot.side_effect = CompleteMarketDataUnavailable('no complete public data')

        with self.assertRaises(CompleteMarketDataUnavailable):
            read_sector_momentum(self.next_trade_date)

    @patch('core.services.sync_daily_prices.sync_stock_daily_prices')
    @patch('sector_momentum.services.read_path.get_complete_market_snapshot')
    def test_absent_public_data_never_starts_remote_full_market_sync(self, snapshot, sync):
        SectorMomentumRanking.objects.using('sector_momentum').all().delete()
        SectorMomentumResult.objects.using('sector_momentum').all().delete()
        snapshot.side_effect = CompleteMarketDataUnavailable('no complete public data')

        with self.assertRaises(CompleteMarketDataUnavailable):
            read_sector_momentum(self.trade_date)

        sync.assert_not_called()

    @patch('sector_momentum.services.read_path.get_complete_industry_snapshot_version')
    @patch('sector_momentum.services.read_path.latest_complete_stock_price_date')
    @patch('sector_momentum.services.read_path.get_complete_market_snapshot')
    def test_default_entry_follows_the_newest_public_date_and_generates_it(
        self, snapshot, latest_public, industry
    ):
        SectorMomentumRanking.objects.using('sector_momentum').all().delete()
        SectorMomentumResult.objects.using('sector_momentum').all().delete()
        latest_public.return_value = self.next_trade_date
        snapshot.return_value = self._snapshot(
            version='daily-prices-20260909-v1', trade_date=self.next_trade_date
        )
        industry.return_value = 'industries-v2'

        result = read_sector_momentum()

        self.assertEqual(result.business_date, self.next_trade_date)
        self.assertEqual(result.source, 'computed')
        self.assertEqual(result.data_version, 'daily-prices-20260909-v1:industries-v2')

    @patch('sector_momentum.services.read_path.latest_complete_stock_price_date')
    @patch('sector_momentum.services.read_path.get_complete_market_snapshot')
    def test_default_entry_falls_back_to_stored_result_marked_stale(
        self, snapshot, latest_public
    ):
        latest_public.return_value = self.next_trade_date
        snapshot.side_effect = CompleteMarketDataUnavailable('no complete public data')

        result = read_sector_momentum()

        self.assertEqual(result.business_date, self.trade_date)
        self.assertTrue(result.stale)
        self.assertEqual(result.source, 'database')
        self.assertIn(
            '公共行情或开盘啦行业映射已更新，正在展示最近可用的分析结果。', result.warnings
        )

    @patch('sector_momentum.services.read_path.get_complete_industry_snapshot_version')
    @patch('sector_momentum.services.read_path.get_complete_market_snapshot')
    def test_absent_industry_snapshot_keeps_the_stale_result_instead_of_failing(
        self, snapshot, industry
    ):
        self._complete_version('stock_daily_prices', 'daily-prices-v2')
        snapshot.return_value = self._snapshot()
        industry.side_effect = CompleteIndustrySnapshotUnavailable('no industry snapshot')

        result = read_sector_momentum(self.trade_date)

        self.assertEqual(result.business_date, self.trade_date)
        self.assertEqual(result.source, 'database')
        self.assertTrue(result.stale)
        self.assertEqual(result.data_version, 'daily-prices-v1:industries-v1')

    @patch('sector_momentum.services.read_path.latest_complete_stock_price_date')
    @patch('sector_momentum.services.read_path.dataset_lock')
    def test_busy_dataset_lock_returns_stored_result_instead_of_raising(
        self, lock, latest_public
    ):
        latest_public.return_value = self.next_trade_date
        lock.side_effect = DatasetLocked('sector_momentum:sector_momentum is already running.')

        result = read_sector_momentum()

        self.assertEqual(result.business_date, self.trade_date)
        self.assertTrue(result.stale)

    @patch('sector_momentum.services.read_path.latest_complete_stock_price_date')
    @patch('sector_momentum.services.read_path.dataset_lock')
    def test_busy_dataset_lock_without_any_result_is_a_409(self, lock, latest_public):
        """Nothing stored and a concurrent run in flight: 409, not 202/404.

        数据集正被另一个进程写出来时，"数据不可用"（404）和"正在准备"（202）都在
        骗客户端去等一件已经有人在做的事。规格 §5.7 的 409 SYNC_IN_PROGRESS 才是
        它的语义，四个业务模块现在给出同一个答案。
        """
        SectorMomentumRanking.objects.using('sector_momentum').all().delete()
        SectorMomentumResult.objects.using('sector_momentum').all().delete()
        latest_public.return_value = self.next_trade_date
        lock.side_effect = DatasetLocked('sector_momentum:sector_momentum is already running.')

        with self.assertRaises(ApiError) as caught:
            read_sector_momentum()

        self.assertEqual(caught.exception.http_status, 409)
        self.assertEqual(caught.exception.code, ErrorCode.SYNC_IN_PROGRESS)
        self.assertEqual(caught.exception.preparation_state, 'syncing')

    @patch('sector_momentum.services.read_path.dataset_lock')
    def test_an_explicit_busy_date_is_not_answered_with_another_days_result(self, lock):
        """显式指定日期又被占用：绝不拿别的日期的结果顶替，而是 409。"""
        lock.side_effect = DatasetLocked('sector_momentum:sector_momentum is already running.')

        with self.assertRaises(ApiError) as caught:
            read_sector_momentum(self.next_trade_date)

        self.assertEqual(caught.exception.http_status, 409)
        self.assertEqual(caught.exception.code, ErrorCode.SYNC_IN_PROGRESS)

    @patch('sector_momentum.services.read_path.get_complete_industry_snapshot_version')
    @patch('sector_momentum.services.read_path.get_complete_market_snapshot')
    def test_stale_result_is_regenerated_when_daily_or_industry_version_changes(
        self, snapshot, industry
    ):
        self._complete_version('stock_daily_prices', 'daily-prices-v2')
        self._complete_version('industry_snapshot', 'industries-v2')
        snapshot.return_value = self._snapshot()
        industry.return_value = 'industries-v2'

        result = read_sector_momentum(self.trade_date)

        self.assertEqual(result.source, 'computed')
        self.assertFalse(result.stale)
        self.assertEqual(result.data_version, 'daily-prices-v2:industries-v2')
