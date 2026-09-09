from datetime import date
from decimal import Decimal
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import TestCase, override_settings

from core.models import DataVersion
from core.services.cache_keys import build_cache_key
from core.services.contracts import CompleteMarketSnapshot, MarketDataVersion, MarketPrice
from core.services.file_cache import FileCache
from core.services.market_data import CompleteMarketDataUnavailable
from stock_moves.models import StockMoveItem, StockMoveResult
from stock_moves.services.read_path import read_stock_moves


class StockMovesFallbackTests(TestCase):
    databases = {'default', 'stock_moves'}

    def setUp(self):
        self.trade_date = date(2026, 9, 8)
        self.result = StockMoveResult.objects.using('stock_moves').create(
            business_date=self.trade_date,
            source_daily_price_version='daily-prices-20260908-v1',
            sse_rise_count=1,
            distinct_stock_count=1,
        )
        StockMoveItem.objects.using('stock_moves').create(
            result=self.result,
            group=StockMoveItem.Group.SSE_RISE,
            rank=1,
            stock_code='600001',
            stock_name='上证上涨',
            parent_industries=[],
            change_percent=Decimal('9'),
            turnover=Decimal('900000000'),
        )
        self.cache_directory = TemporaryDirectory()
        self.cache = FileCache(self.cache_directory.name, ttl_seconds=300, max_bytes=1_000_000)
        self.addCleanup(self.cache_directory.cleanup)

    def _snapshot(self, count=1, version='daily-prices-20260908-v2'):
        prices = tuple(
            MarketPrice(
                stock_code=f'600{number:03d}',
                thscode=f'600{number:03d}.SH',
                stock_name=f'股票{number}',
                exchange='sse',
                trade_date=self.trade_date,
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
            data_version=MarketDataVersion(version=version, business_date=self.trade_date),
            prices=prices,
            parent_industries=(),
        )

    @patch('stock_moves.services.read_path.default_file_cache')
    def test_corrupted_cache_falls_back_to_database_data(self, cache_factory):
        cache_factory.return_value = self.cache
        key = build_cache_key(
            'stock_moves', 'result', {'date': '2026-09-08'}, 'daily-prices-20260908-v1'
        )
        path = self.cache.path_for(key)
        path.parent.mkdir(parents=True)
        path.write_text('{not json', encoding='utf-8')

        result = read_stock_moves(self.trade_date)

        self.assertEqual(result.source, 'database')
        self.assertEqual(result.data['stock_codes'], ['600001'])

    @patch('stock_moves.services.read_path.default_file_cache', return_value=None)
    @patch('stock_moves.services.read_path.get_complete_market_snapshot')
    @patch.dict('os.environ', {'REMOTE_REPAIR_MAX_ROWS': '10'}, clear=False)
    def test_missing_result_rebuilds_from_small_local_public_snapshot(self, snapshot, _cache_factory):
        StockMoveItem.objects.using('stock_moves').all().delete()
        StockMoveResult.objects.using('stock_moves').all().delete()
        snapshot.return_value = self._snapshot()

        result = read_stock_moves(self.trade_date)

        self.assertEqual(result.source, 'computed')
        self.assertEqual(result.data_version, 'daily-prices-20260908-v2')
        self.assertTrue(StockMoveResult.objects.using('stock_moves').filter(
            source_daily_price_version='daily-prices-20260908-v2'
        ).exists())

    @patch('core.services.sync_daily_prices.sync_stock_daily_prices')
    @patch('stock_moves.services.read_path.get_complete_market_snapshot')
    def test_absent_public_data_never_starts_remote_full_market_sync(self, snapshot, sync):
        StockMoveItem.objects.using('stock_moves').all().delete()
        StockMoveResult.objects.using('stock_moves').all().delete()
        snapshot.side_effect = CompleteMarketDataUnavailable('no complete public data')

        with self.assertRaises(CompleteMarketDataUnavailable):
            read_stock_moves(self.trade_date)

        sync.assert_not_called()

    @patch('stock_moves.services.read_path.get_complete_market_snapshot')
    @patch.dict('os.environ', {'REMOTE_REPAIR_MAX_ROWS': '1'}, clear=False)
    def test_large_local_rebuild_is_refused_so_web_requests_stay_bounded(self, snapshot):
        StockMoveItem.objects.using('stock_moves').all().delete()
        StockMoveResult.objects.using('stock_moves').all().delete()
        snapshot.return_value = self._snapshot(count=2)

        with self.assertRaises(CompleteMarketDataUnavailable):
            read_stock_moves(self.trade_date)

    @patch('stock_moves.services.read_path.get_complete_market_snapshot')
    @patch.dict('os.environ', {'REMOTE_REPAIR_MAX_ROWS': '10'}, clear=False)
    def test_stale_result_rebuilds_when_new_public_version_is_small_enough(self, snapshot):
        DataVersion.objects.create(
            dataset_key='stock_daily_prices',
            version='daily-prices-20260908-v2',
            business_date=self.trade_date,
            status=DataVersion.Status.COMPLETE,
            expected_record_count=1,
            actual_record_count=1,
        )
        snapshot.return_value = self._snapshot()

        result = read_stock_moves(self.trade_date)

        self.assertEqual(result.source, 'computed')
        self.assertFalse(result.stale)
        self.assertEqual(result.data_version, 'daily-prices-20260908-v2')
