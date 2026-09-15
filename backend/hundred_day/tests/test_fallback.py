from datetime import date, timedelta
from decimal import Decimal
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from core.api.errors import ApiError, ErrorCode
from core.models import IndustrySnapshot
from core.services.contracts import Industry
from core.services.file_cache import FileCache
from core.services.locking import DatasetLocked
from core.services.market_data import CompleteMarketDataUnavailable
from hundred_day.models import HundredDayBreadth, HundredDayIndustrySummary
from hundred_day.services.analysis import (
    HistoricalCloseData,
    InsufficientHundredDayHistory,
    TargetDayQuote,
)
from hundred_day.services.read_path import read_hundred_day


class HundredDayFallbackTests(TestCase):
    databases = {'default', 'hundred_day'}

    business_date = date(2026, 9, 8)
    next_business_date = date(2026, 9, 9)

    def setUp(self):
        # 行业归属决定板块汇总怎么分组，本地生成前会先确认它在库里。
        IndustrySnapshot.objects.create(
            industry_code='I001', industry_name='电子', stock_codes=['600001']
        )
        # "已有一份结果"现在就是"这一天有一个市场宽度点"：业务日期那一行即当日汇总。
        self.stored = HundredDayBreadth.objects.using('hundred_day').create(
            business_date=self.business_date,
            trade_date=self.business_date,
            valid_stock_count=1,
            new_high_count=1,
            published_at=timezone.now(),
        )
        # 默认文件缓存会落到磁盘并在多次运行之间复用，会让 source 断言变得不确定；
        # 这里统一关掉，只有显式验证缓存行为的用例再用装饰器打开。
        cache_patch = patch('hundred_day.services.read_path.default_file_cache', return_value=None)
        cache_patch.start()
        self.addCleanup(cache_patch.stop)

    def _source(self, positions=100, business_date=None):
        day = business_date or self.business_date
        days = tuple(
            day - timedelta(days=positions - index - 1) for index in range(positions)
        )
        return HistoricalCloseData(
            business_date=day,
            trading_days=days,
            close_prices_by_stock={
                '600001': {value: Decimal('10') for value in days[:-1]}
                | {days[-1]: Decimal('11')}
            },
            stock_names_by_code={'600001': '测试股票'},
            industries=(Industry('I001', '电子', ('600001',)),),
            target_day_quotes={'600001': TargetDayQuote(Decimal('10'), Decimal('1000000'))},
        )

    @patch('hundred_day.services.read_path.load_hundred_day_source_data')
    def test_missing_result_is_generated_from_local_source_data(self, source):
        HundredDayBreadth.objects.using('hundred_day').all().delete()
        source.return_value = self._source()

        result = read_hundred_day(self.business_date)

        self.assertEqual(result.source, 'computed')
        self.assertFalse(result.stale)
        self.assertEqual(
            HundredDayBreadth.objects.using('hundred_day')
            .filter(business_date=self.business_date).count(),
            1,
        )

    @patch('hundred_day.services.read_path.load_hundred_day_source_data')
    def test_a_day_with_no_flags_still_renders(self, source):
        """一天没有一只股票被标记时，市场宽度那一点仍然在，所以页面读得出这一天。

        与 stock_moves / sector_momentum 不同，这里不需要"空日期"兜底：宽度点是按
        分析窗口的交易日逐日写下来的，与被标记的股票无关。
        """
        HundredDayBreadth.objects.using('hundred_day').all().delete()
        HundredDayBreadth.objects.using('hundred_day').create(
            business_date=self.business_date,
            trade_date=self.business_date,
            valid_stock_count=0,
            published_at=timezone.now(),
        )
        HundredDayIndustrySummary.objects.using('hundred_day').create(
            business_date=self.business_date,
            industry_code='I001',
            industry_name='电子',
            stock_count=1,
        )
        source.side_effect = AssertionError('a stored day must not be regenerated')

        result = read_hundred_day(self.business_date)

        self.assertEqual(result.source, 'database')
        self.assertEqual(result.data['totals'], {
            'valid_stock_count': 0,
            'new_high_count': 0,
            'new_low_count': 0,
            'new_high_ratio': None,
            'new_low_ratio': None,
        })
        summary = result.data['industry_summaries'][0]
        self.assertEqual(summary['stock_count'], 1)
        self.assertEqual(summary['new_high_count'], 0)
        self.assertEqual(summary['new_high_stocks'], [])

    @patch('hundred_day.services.read_path.load_hundred_day_source_data')
    def test_missing_industry_mapping_makes_the_day_unavailable(self, source):
        """没有行业映射就没有板块分组：宁可"不可用"，也不落一份空汇总。"""
        HundredDayBreadth.objects.using('hundred_day').all().delete()
        IndustrySnapshot.objects.all().delete()
        source.return_value = self._source()

        with self.assertRaises(CompleteMarketDataUnavailable):
            read_hundred_day(self.business_date)

        self.assertFalse(HundredDayBreadth.objects.using('hundred_day').exists())

    @patch('hundred_day.services.read_path.load_hundred_day_source_data')
    def test_a_stored_result_is_served_without_regenerating_it(self, source):
        """结果按业务日期唯一，读路径不做任何"是否过期"的比较。"""
        source.side_effect = AssertionError('a stored result must not be regenerated')

        result = read_hundred_day(self.business_date)

        self.assertEqual(result.source, 'database')
        self.assertFalse(result.stale)

    @patch('hundred_day.services.read_path.load_hundred_day_source_data')
    def test_long_history_is_generated_without_a_row_budget(self, source):
        """The local generation path is a computation, not a bounded remote repair."""
        HundredDayBreadth.objects.using('hundred_day').all().delete()
        source.return_value = self._source(positions=199)

        result = read_hundred_day(self.business_date)

        self.assertEqual(result.source, 'computed')
        self.assertEqual(result.data['totals']['new_high_count'], 1)
        self.assertEqual(len(result.data['trend']), 100)
        self.assertEqual(
            HundredDayBreadth.objects.using('hundred_day')
            .filter(business_date=self.business_date).count(),
            100,
        )

    @patch('hundred_day.services.read_path.load_hundred_day_source_data')
    def test_insufficient_history_is_unavailable_on_an_explicit_date(self, source):
        HundredDayBreadth.objects.using('hundred_day').all().delete()
        source.return_value = self._source(positions=99)

        with self.assertRaises(InsufficientHundredDayHistory):
            read_hundred_day(self.business_date)

    @patch('hundred_day.services.read_path.latest_complete_stock_price_date')
    @patch('hundred_day.services.read_path.load_hundred_day_source_data')
    def test_default_entry_follows_the_newest_public_date_and_generates_it(
        self, source, latest_public
    ):
        HundredDayBreadth.objects.using('hundred_day').all().delete()
        latest_public.return_value = self.next_business_date
        source.return_value = self._source(business_date=self.next_business_date)

        result = read_hundred_day()

        self.assertEqual(result.business_date, self.next_business_date)
        self.assertEqual(result.source, 'computed')

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
            '正在展示最近可用的百日分析结果，当日结果可能尚未生成。',
            result.warnings,
        )

    @patch('core.services.sync_daily_prices.HithinkClient')
    @patch('hundred_day.services.read_path.load_hundred_day_source_data')
    def test_absent_source_data_never_starts_an_upstream_fetch(self, source, client):
        """读路径要么用已存的数据回答，要么不回答 —— 绝不自己去抓。

        锚点钉在上游客户端而不是某个命令的服务函数上：这个数据集的每一次抓取都要
        过 ``HithinkClient``，所以换了入口（例如历史同步命令被删掉、只剩盘中刷新）
        这条不变量依然守着，新加的命令也绕不过去。
        """
        HundredDayBreadth.objects.using('hundred_day').all().delete()
        source.side_effect = CompleteMarketDataUnavailable('no local history')

        with self.assertRaises(CompleteMarketDataUnavailable):
            read_hundred_day(self.business_date)

        client.assert_not_called()

    @patch('hundred_day.services.read_path.default_file_cache')
    def test_the_data_time_is_reported_from_both_database_and_cache(self, cache_factory):
        """信封里的数据时刻来自库里那一行，命中文件缓存时也一样。

        缓存里存的是载荷、不是信封 —— 信封每次请求都重建，所以时间戳必须在缓存分支
        里显式带上。漏掉的表现是"页面刷过一次之后，胶囊上的时刻就没了"。这条同时把
        三条断言的坐标钉死：它是**写入时刻**，不是 `timezone.now()`。
        """
        with TemporaryDirectory() as directory:
            cache_factory.return_value = FileCache(
                directory, ttl_seconds=300, max_bytes=1_000_000
            )
            written_at = timezone.now() - timedelta(days=30)
            HundredDayBreadth.objects.using('hundred_day').filter(pk=self.stored.pk).update(
                published_at=written_at
            )

            first = read_hundred_day(self.business_date)
            second = read_hundred_day(self.business_date)

        self.assertEqual(first.source, 'database')
        self.assertEqual(second.source, 'cache')
        self.assertEqual(first.data_updated_at, written_at)
        self.assertEqual(second.data_updated_at, written_at)

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
        HundredDayBreadth.objects.using('hundred_day').all().delete()
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
