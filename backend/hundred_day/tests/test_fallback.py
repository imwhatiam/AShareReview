from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from core.api.errors import ApiError, ErrorCode
from core.models import DataVersion
from core.services.contracts import MarketDataVersion, Industry
from core.services.locking import DatasetLocked
from core.services.market_data import CompleteMarketDataUnavailable
from hundred_day.models import HundredDayResult
from hundred_day.services.analysis import (
    HistoricalCloseData,
    InsufficientHundredDayHistory,
    TargetDayQuote,
)
from hundred_day.services.read_path import read_hundred_day
from hundred_day.services.source_versions import CompleteIndustrySnapshotUnavailable


class HundredDayFallbackTests(TestCase):
    databases = {'default', 'hundred_day'}

    business_date = date(2026, 9, 8)
    next_business_date = date(2026, 9, 9)

    def setUp(self):
        self.stored = HundredDayResult.objects.using('hundred_day').create(
            business_date=self.business_date,
            source_daily_price_version='daily-prices-v1',
            source_industry_version='industries-v1',
            valid_stock_count=1,
            new_high_count=1,
        )
        # 默认文件缓存会落到磁盘并在多次运行之间复用，会让 source 断言变得不确定；
        # 这里统一关掉，只有显式验证缓存行为的用例再用装饰器打开。
        cache_patch = patch('hundred_day.services.read_path.default_file_cache', return_value=None)
        cache_patch.start()
        self.addCleanup(cache_patch.stop)

    def _source(self, positions=100, business_date=None, version='daily-prices-v2'):
        day = business_date or self.business_date
        days = tuple(
            day - timedelta(days=positions - index - 1) for index in range(positions)
        )
        return HistoricalCloseData(
            data_version=MarketDataVersion(version, day),
            trading_days=days,
            close_prices_by_stock={
                '600001': {value: Decimal('10') for value in days[:-1]}
                | {days[-1]: Decimal('11')}
            },
            stock_names_by_code={'600001': '测试股票'},
            industries=(Industry('I001', '电子', ('600001',)),),
            target_day_quotes={'600001': TargetDayQuote(Decimal('10'), Decimal('1000000'))},
        )

    def _complete_version(self, dataset_key, version, business_date=None):
        return DataVersion.objects.create(
            dataset_key=dataset_key,
            version=version,
            business_date=business_date or self.business_date,
            status=DataVersion.Status.COMPLETE,
            expected_record_count=1,
            actual_record_count=1,
        )

    @patch('hundred_day.services.read_path.get_complete_industry_snapshot_version')
    @patch('hundred_day.services.read_path.load_hundred_day_source_data')
    def test_missing_result_is_generated_from_local_source_data(self, source, industry):
        source.return_value = self._source()
        industry.return_value = 'industries-v2'

        result = read_hundred_day(self.business_date)

        self.assertEqual(result.source, 'computed')
        self.assertFalse(result.stale)
        self.assertEqual(result.data_version, 'daily-prices-v2:industries-v2')
        self.assertTrue(HundredDayResult.objects.using('hundred_day').filter(
            source_daily_price_version='daily-prices-v2',
            source_industry_version='industries-v2',
        ).exists())

    @patch('hundred_day.services.read_path.get_complete_industry_snapshot_version')
    @patch('hundred_day.services.read_path.load_hundred_day_source_data')
    def test_long_history_is_generated_without_a_row_budget(self, source, industry):
        """The local generation path is a computation, not a bounded remote repair."""
        source.return_value = self._source(positions=199)
        industry.return_value = 'industries-v2'

        result = read_hundred_day(self.business_date)

        self.assertEqual(result.source, 'computed')
        self.assertEqual(result.data['totals']['new_high_count'], 1)
        self.assertTrue(result.data['trend'])

    @patch('hundred_day.services.read_path.get_complete_industry_snapshot_version')
    @patch('hundred_day.services.read_path.load_hundred_day_source_data')
    def test_insufficient_history_is_unavailable_on_an_explicit_date(self, source, industry):
        HundredDayResult.objects.using('hundred_day').all().delete()
        source.return_value = self._source(positions=99)
        industry.return_value = 'industries-v1'

        with self.assertRaises(InsufficientHundredDayHistory):
            read_hundred_day(self.business_date)

    @patch('hundred_day.services.read_path.get_complete_industry_snapshot_version')
    @patch('hundred_day.services.read_path.latest_complete_stock_price_date')
    @patch('hundred_day.services.read_path.load_hundred_day_source_data')
    def test_default_entry_follows_the_newest_public_date_and_generates_it(
        self, source, latest_public, industry
    ):
        HundredDayResult.objects.using('hundred_day').all().delete()
        latest_public.return_value = self.next_business_date
        source.return_value = self._source(
            business_date=self.next_business_date, version='daily-prices-20260909-v1'
        )
        industry.return_value = 'industries-v2'

        result = read_hundred_day()

        self.assertEqual(result.business_date, self.next_business_date)
        self.assertEqual(result.source, 'computed')
        self.assertEqual(result.data_version, 'daily-prices-20260909-v1:industries-v2')

    @patch('hundred_day.services.read_path.latest_complete_stock_price_date')
    @patch('hundred_day.services.read_path.load_hundred_day_source_data')
    def test_default_entry_falls_back_to_stored_result_marked_stale(self, source, latest_public):
        latest_public.return_value = self.next_business_date
        source.side_effect = InsufficientHundredDayHistory('not enough history')

        result = read_hundred_day()

        self.assertEqual(result.business_date, self.business_date)
        self.assertTrue(result.stale)
        self.assertEqual(result.source, 'database')
        self.assertIn(
            '公共日行情或行业映射版本已更新，正在展示最近可用的百日分析结果。',
            result.warnings,
        )

    @patch('core.services.sync_daily_prices.sync_stock_daily_prices')
    @patch('hundred_day.services.read_path.load_hundred_day_source_data')
    def test_absent_source_data_never_starts_remote_full_market_sync(self, source, sync):
        HundredDayResult.objects.using('hundred_day').all().delete()
        source.side_effect = CompleteMarketDataUnavailable('no local history')

        with self.assertRaises(CompleteMarketDataUnavailable):
            read_hundred_day(self.business_date)

        sync.assert_not_called()

    @patch('hundred_day.services.read_path.get_complete_industry_snapshot_version')
    @patch('hundred_day.services.read_path.load_hundred_day_source_data')
    def test_absent_industry_snapshot_keeps_the_stale_result_instead_of_failing(
        self, source, industry
    ):
        self._complete_version('stock_daily_prices', 'daily-prices-v2')
        source.return_value = self._source()
        industry.side_effect = CompleteIndustrySnapshotUnavailable('no industry snapshot')

        result = read_hundred_day(self.business_date)

        self.assertEqual(result.business_date, self.business_date)
        self.assertEqual(result.source, 'database')
        self.assertTrue(result.stale)
        self.assertEqual(result.data_version, 'daily-prices-v1:industries-v1')

    @patch('hundred_day.services.read_path.latest_complete_stock_price_date')
    @patch('hundred_day.services.read_path.dataset_lock')
    def test_busy_dataset_lock_returns_stored_result_instead_of_raising(
        self, lock, latest_public
    ):
        latest_public.return_value = self.next_business_date
        lock.side_effect = DatasetLocked('hundred_day:hundred_day is already running.')

        result = read_hundred_day()

        self.assertEqual(result.business_date, self.business_date)
        self.assertTrue(result.stale)

    @patch('hundred_day.services.read_path.latest_complete_stock_price_date')
    @patch('hundred_day.services.read_path.dataset_lock')
    def test_busy_dataset_lock_without_any_result_is_a_409(self, lock, latest_public):
        """Nothing stored and a concurrent run in flight: 409, not 202/404.

        数据集正被另一个进程写出来时，"数据不可用"（404）和"正在准备"（202）都在
        骗客户端去等一件已经有人在做的事。规格 §5.7 的 409 SYNC_IN_PROGRESS 才是
        它的语义，四个业务模块现在给出同一个答案。
        """
        HundredDayResult.objects.using('hundred_day').all().delete()
        latest_public.return_value = self.next_business_date
        lock.side_effect = DatasetLocked('hundred_day:hundred_day is already running.')

        with self.assertRaises(ApiError) as caught:
            read_hundred_day()

        self.assertEqual(caught.exception.http_status, 409)
        self.assertEqual(caught.exception.code, ErrorCode.SYNC_IN_PROGRESS)
        self.assertEqual(caught.exception.preparation_state, 'syncing')

    @patch('hundred_day.services.read_path.dataset_lock')
    def test_an_explicit_busy_date_is_not_answered_with_another_days_result(self, lock):
        """显式指定日期又被占用：绝不拿别的日期的结果顶替，而是 409。"""
        lock.side_effect = DatasetLocked('hundred_day:hundred_day is already running.')

        with self.assertRaises(ApiError) as caught:
            read_hundred_day(self.next_business_date)

        self.assertEqual(caught.exception.http_status, 409)
        self.assertEqual(caught.exception.code, ErrorCode.SYNC_IN_PROGRESS)

    @patch('hundred_day.services.read_path.get_complete_industry_snapshot_version')
    @patch('hundred_day.services.read_path.load_hundred_day_source_data')
    def test_stale_result_is_regenerated_when_new_versions_arrive(self, source, industry):
        self._complete_version('stock_daily_prices', 'daily-prices-v2')
        self._complete_version('industry_snapshot', 'industries-v2')
        source.return_value = self._source()
        industry.return_value = 'industries-v2'

        result = read_hundred_day(self.business_date)

        self.assertEqual(result.source, 'computed')
        self.assertFalse(result.stale)
        self.assertEqual(result.data_version, 'daily-prices-v2:industries-v2')
