from datetime import date
from decimal import Decimal
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from core.services.file_cache import FileCache
from stock_moves.models import StockMoveItem, StockMoveResult


class StockMovesApiTests(TestCase):
    databases = {'default', 'stock_moves'}

    def setUp(self):
        self.trade_date = date(2026, 9, 8)
        self.user = get_user_model().objects.create_user(
            username='stock-moves-user', password='correct-password'
        )
        self.result = StockMoveResult.objects.using('stock_moves').create(
            business_date=self.trade_date,
            source_daily_price_version='daily-prices-20260908-v1',
            sse_rise_count=1,
            sse_fall_count=0,
            szse_rise_count=1,
            szse_fall_count=0,
            distinct_stock_count=2,
            warnings=['股票 000001 未映射到开盘啦父行业。'],
        )
        StockMoveItem.objects.using('stock_moves').bulk_create([
            StockMoveItem(
                result=self.result,
                group=StockMoveItem.Group.SSE_RISE,
                rank=1,
                stock_code='600001',
                stock_name='上证上涨',
                parent_industries=[{'code': 'I001', 'name': '银行'}],
                change_percent=Decimal('9'),
                turnover=Decimal('900000000'),
            ),
            StockMoveItem(
                result=self.result,
                group=StockMoveItem.Group.SZSE_RISE,
                rank=1,
                stock_code='000001',
                stock_name='深证上涨',
                parent_industries=[],
                change_percent=Decimal('8'),
                turnover=Decimal('800000000'),
            ),
        ])
        self.cache_directory = TemporaryDirectory()
        self.cache = FileCache(self.cache_directory.name, ttl_seconds=300, max_bytes=1_000_000)
        self.addCleanup(self.cache_directory.cleanup)

    def _authenticated_client(self):
        self.client.force_login(self.user)
        return self.client

    def test_endpoints_require_an_authenticated_session(self):
        response = self.client.get('/api/stock-moves/')

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['error']['code'], 'AUTH_REQUIRED')

    @patch('stock_moves.services.read_path.default_file_cache')
    def test_result_reads_database_then_file_cache_with_the_shared_envelope(self, cache_factory):
        cache_factory.return_value = self.cache

        first = self._authenticated_client().get('/api/stock-moves/?date=2026-09-08')
        second = self._authenticated_client().get('/api/stock-moves/?date=2026-09-08')

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()['status'], 'partial')
        self.assertEqual(first.json()['business_date'], '2026-09-08')
        self.assertEqual(first.json()['data_version'], 'daily-prices-20260908-v1')
        self.assertEqual(first.json()['source'], 'database')
        self.assertEqual(
            first.json()['data']['group_counts'],
            {'sse_rise': 1, 'sse_fall': 0, 'szse_rise': 1, 'szse_fall': 0},
        )
        self.assertEqual(first.json()['data']['stock_codes'], ['000001', '600001'])
        self.assertEqual(
            first.json()['data']['groups']['sse_rise'][0]['parent_industries'],
            [{'code': 'I001', 'name': '银行'}],
        )
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()['source'], 'cache')
        self.assertEqual(second.json()['data'], first.json()['data'])

    def test_explicit_invalid_or_unavailable_dates_are_rejected_without_silent_fallback(self):
        client = self._authenticated_client()

        malformed = client.get('/api/stock-moves/?date=2026-9-8')
        unavailable = client.get('/api/stock-moves/?date=2026-09-07')

        self.assertEqual(malformed.status_code, 400)
        self.assertEqual(malformed.json()['error']['code'], 'INVALID_DATE')
        self.assertEqual(unavailable.status_code, 404)
        self.assertEqual(unavailable.json()['error']['code'], 'DATA_NOT_AVAILABLE')

    @patch('stock_moves.services.read_path.default_file_cache')
    def test_dates_lists_distinct_available_result_dates(self, cache_factory):
        cache_factory.return_value = self.cache
        StockMoveResult.objects.using('stock_moves').create(
            business_date=date(2026, 9, 7),
            source_daily_price_version='daily-prices-20260907-v1',
        )

        response = self._authenticated_client().get('/api/stock-moves/dates/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['dates'], ['2026-09-08', '2026-09-07'])
        self.assertEqual(response.json()['source'], 'database')
