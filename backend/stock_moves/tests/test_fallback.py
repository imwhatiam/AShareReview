from datetime import date
from decimal import Decimal
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from core.api.errors import ApiError, ErrorCode
from core.models import IndustrySnapshot
from core.services.cache_keys import build_cache_key
from core.services.contracts import CompleteMarketSnapshot, MarketPrice
from core.services.file_cache import FileCache
from core.services.locking import DatasetLocked
from core.services.market_data import CompleteMarketDataUnavailable
from stock_moves.models import StockMoveItem
from stock_moves.services.read_path import read_stock_moves


class StockMovesFallbackTests(TestCase):
    databases = {'default', 'stock_moves'}

    def setUp(self):
        self.trade_date = date(2026, 9, 8)
        self.next_trade_date = date(2026, 9, 9)
        # 行业映射是第二个输入，本地生成前会先确认它在库里。
        IndustrySnapshot.objects.create(
            industry_code='I001', industry_name='银行', stock_codes=['600001']
        )
        self.published_at = timezone.now()
        self.item = StockMoveItem.objects.using('stock_moves').create(
            business_date=self.trade_date,
            group=StockMoveItem.Group.SSE_RISE,
            rank=1,
            stock_code='600001',
            stock_name='上证上涨',
            industries=[],
            change_percent=Decimal('9'),
            turnover=Decimal('900000000'),
            published_at=self.published_at,
        )
        self.cache_directory = TemporaryDirectory()
        self.cache = FileCache(self.cache_directory.name, ttl_seconds=300, max_bytes=1_000_000)
        self.addCleanup(self.cache_directory.cleanup)
        # 默认文件缓存会落到磁盘并在多次运行之间复用，会让 source 断言变得不确定；
        # 这里统一关掉，只有显式验证缓存行为的用例再用装饰器打开。
        cache_patch = patch('stock_moves.services.read_path.default_file_cache', return_value=None)
        cache_patch.start()
        self.addCleanup(cache_patch.stop)

    def _snapshot(self, count=1, trade_date=None):
        day = trade_date or self.trade_date
        prices = tuple(
            MarketPrice(
                stock_code=f'600{number:03d}',
                thscode=f'600{number:03d}.SH',
                stock_name=f'股票{number}',
                exchange='sse',
                trade_date=day,
                pre_close=None,
                open_price=None,
                high_price=None,
                low_price=None,
                close_price=None,
                change_percent=Decimal('8'),
                volume=None,
                turnover=Decimal('800000000'),
                has_valid_trade=True,
            )
            for number in range(1, count + 1)
        )
        return CompleteMarketSnapshot(
            business_date=day,
            prices=prices,
            industries=(),
        )

    @patch('stock_moves.services.read_path.default_file_cache')
    def test_corrupted_cache_falls_back_to_database_data(self, cache_factory):
        cache_factory.return_value = self.cache
        # 缓存身份 = 所服务那一行的发布时间，不是版本号。
        key = build_cache_key(
            'stock_moves', 'result', {'date': '2026-09-08'},
            self.item.published_at.isoformat(),
        )
        path = self.cache.path_for(key)
        path.parent.mkdir(parents=True)
        path.write_text('{not json', encoding='utf-8')

        result = read_stock_moves(self.trade_date)

        self.assertEqual(result.source, 'database')
        self.assertEqual(result.data['stock_codes'], ['600001'])

    @patch('stock_moves.services.read_path.get_complete_market_snapshot')
    def test_missing_result_is_generated_from_local_public_snapshot(self, snapshot):
        StockMoveItem.objects.using('stock_moves').all().delete()
        snapshot.return_value = self._snapshot()

        result = read_stock_moves(self.trade_date)

        self.assertEqual(result.source, 'computed')
        self.assertFalse(result.stale)
        self.assertEqual(
            StockMoveItem.objects.using('stock_moves')
            .filter(business_date=self.trade_date).count(),
            1,
        )

    @patch('stock_moves.services.read_path.get_complete_market_snapshot')
    def test_missing_industry_mapping_makes_the_day_unavailable(self, snapshot):
        """没有行业映射就生成不了：宁可"不可用"，也不落一份缺 industries 的结果。"""
        StockMoveItem.objects.using('stock_moves').all().delete()
        IndustrySnapshot.objects.all().delete()
        snapshot.return_value = self._snapshot()

        with self.assertRaises(CompleteMarketDataUnavailable):
            read_stock_moves(self.trade_date)

        self.assertFalse(StockMoveItem.objects.using('stock_moves').exists())

    @patch('stock_moves.services.read_path.get_complete_market_snapshot')
    def test_a_day_whose_stocks_all_miss_the_thresholds_renders_an_empty_board(self, snapshot):
        """一天没有任何股票达标时表里没有行，但这一天仍然要能读出空看板。"""
        StockMoveItem.objects.using('stock_moves').all().delete()
        snapshot.return_value = CompleteMarketSnapshot(
            business_date=self.trade_date, prices=(), industries=()
        )

        result = read_stock_moves(self.trade_date)

        self.assertEqual(result.source, 'computed')
        self.assertEqual(result.data['stock_codes'], [])
        self.assertEqual(result.data['distinct_stock_count'], 0)
        self.assertEqual(
            set(result.data['group_counts'].values()), {0},
        )
        self.assertFalse(StockMoveItem.objects.using('stock_moves').exists())

    @patch('stock_moves.services.read_path.get_complete_market_snapshot')
    def test_a_stored_result_is_served_without_regenerating_it(self, snapshot):
        """结果按业务日期唯一，读路径不做任何"是否过期"的比较。"""
        snapshot.side_effect = AssertionError('a stored result must not be regenerated')

        result = read_stock_moves(self.trade_date)

        self.assertEqual(result.source, 'database')
        self.assertFalse(result.stale)
        self.assertEqual(result.data['stock_codes'], ['600001'])

    @patch('stock_moves.services.read_path.get_complete_market_snapshot')
    def test_large_snapshot_is_generated_without_a_row_budget(self, snapshot):
        """The local generation path is a computation, not a bounded remote repair."""
        StockMoveItem.objects.using('stock_moves').all().delete()
        snapshot.return_value = self._snapshot(count=5000)

        result = read_stock_moves(self.trade_date)

        self.assertEqual(result.source, 'computed')
        self.assertEqual(result.data['distinct_stock_count'], 5000)

    @patch('stock_moves.services.read_path.get_complete_market_snapshot')
    def test_explicit_date_without_generatable_data_stays_unavailable(self, snapshot):
        """An explicit date must never silently answer with another day's result."""
        snapshot.side_effect = CompleteMarketDataUnavailable('no complete public data')

        with self.assertRaises(CompleteMarketDataUnavailable):
            read_stock_moves(self.next_trade_date)

    @patch('core.services.sync_daily_prices.HithinkClient')
    @patch('stock_moves.services.read_path.get_complete_market_snapshot')
    def test_absent_public_data_never_starts_an_upstream_fetch(self, snapshot, client):
        """读路径要么用已存的数据回答，要么不回答 —— 绝不自己去抓。

        锚点钉在上游客户端而不是某个命令的服务函数上：这个数据集的每一次抓取都要
        过 ``HithinkClient``，所以换了入口（例如历史同步命令被删掉、只剩盘中刷新）
        这条不变量依然守着，新加的命令也绕不过去。
        """
        StockMoveItem.objects.using('stock_moves').all().delete()
        snapshot.side_effect = CompleteMarketDataUnavailable('no complete public data')

        with self.assertRaises(CompleteMarketDataUnavailable):
            read_stock_moves(self.trade_date)

        client.assert_not_called()

    @patch('stock_moves.services.read_path.latest_complete_stock_price_date')
    @patch('stock_moves.services.read_path.get_complete_market_snapshot')
    def test_default_entry_follows_the_newest_public_date_and_generates_it(
        self, snapshot, latest_public
    ):
        StockMoveItem.objects.using('stock_moves').all().delete()
        latest_public.return_value = self.next_trade_date
        snapshot.return_value = self._snapshot(trade_date=self.next_trade_date)

        result = read_stock_moves()

        self.assertEqual(result.business_date, self.next_trade_date)
        self.assertEqual(result.source, 'computed')
        self.assertEqual(result.data['trade_date'], '2026-09-09')

    @patch('stock_moves.services.read_path.latest_complete_stock_price_date')
    @patch('stock_moves.services.read_path.get_complete_market_snapshot')
    def test_default_entry_falls_back_to_stored_result_marked_stale(
        self, snapshot, latest_public
    ):
        latest_public.return_value = self.next_trade_date
        snapshot.side_effect = CompleteMarketDataUnavailable('no complete public data')

        result = read_stock_moves()

        self.assertEqual(result.business_date, self.trade_date)
        self.assertTrue(result.stale)
        self.assertEqual(result.source, 'database')
        self.assertIn(
            '正在展示最近可用的分析结果，当日结果可能尚未生成。', result.warnings
        )

    @patch('stock_moves.services.read_path.latest_complete_stock_price_date')
    @patch('stock_moves.services.read_path.dataset_lock')
    def test_busy_dataset_lock_returns_stored_result_instead_of_raising(
        self, lock, latest_public
    ):
        latest_public.return_value = self.next_trade_date
        lock.side_effect = DatasetLocked('stock_moves:stock_moves is already running.')

        result = read_stock_moves()

        self.assertEqual(result.business_date, self.trade_date)
        self.assertTrue(result.stale)

    @patch('stock_moves.services.read_path.latest_complete_stock_price_date')
    @patch('stock_moves.services.read_path.dataset_lock')
    def test_busy_dataset_lock_without_any_result_is_a_409(self, lock, latest_public):
        """Nothing stored and a concurrent run in flight: 409, not 202/404.

        数据集正被另一个进程写出来时，"数据不可用"（404）和"正在准备"（202）都在
        骗客户端去等一件已经有人在做的事。规格 §5.7 的 409 SYNC_IN_PROGRESS 才是
        它的语义，四个业务模块现在给出同一个答案。
        """
        StockMoveItem.objects.using('stock_moves').all().delete()
        latest_public.return_value = self.next_trade_date
        lock.side_effect = DatasetLocked('stock_moves:stock_moves is already running.')

        with self.assertRaises(ApiError) as caught:
            read_stock_moves()

        self.assertEqual(caught.exception.http_status, 409)
        self.assertEqual(caught.exception.code, ErrorCode.SYNC_IN_PROGRESS)
        self.assertEqual(caught.exception.preparation_state, 'syncing')

    @patch('stock_moves.services.read_path.dataset_lock')
    def test_an_explicit_busy_date_is_not_answered_with_another_days_result(self, lock):
        """显式指定日期又被占用：绝不拿别的日期的结果顶替，而是 409。"""
        lock.side_effect = DatasetLocked('stock_moves:stock_moves is already running.')

        with self.assertRaises(ApiError) as caught:
            read_stock_moves(self.next_trade_date)

        self.assertEqual(caught.exception.http_status, 409)
        self.assertEqual(caught.exception.code, ErrorCode.SYNC_IN_PROGRESS)
