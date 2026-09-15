from datetime import date
from decimal import Decimal
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from core.services.file_cache import FileCache
from stock_moves.models import StockMoveItem


class StockMovesApiTests(TestCase):
    databases = {'default', 'stock_moves'}

    def setUp(self):
        self.trade_date = date(2026, 9, 8)
        self.user = get_user_model().objects.create_user(
            username='stock-moves-user', password='correct-password'
        )
        self.published_at = timezone.now()
        StockMoveItem.objects.using('stock_moves').bulk_create([
            StockMoveItem(
                business_date=self.trade_date,
                group=StockMoveItem.Group.SSE_RISE,
                rank=1,
                stock_code='600001',
                stock_name='上证上涨',
                industries=[{'code': 'I001', 'name': '银行'}],
                change_percent=Decimal('9'),
                turnover=Decimal('900000000'),
                published_at=self.published_at,
            ),
            StockMoveItem(
                business_date=self.trade_date,
                group=StockMoveItem.Group.SZSE_RISE,
                rank=1,
                stock_code='000001',
                stock_name='深证上涨',
                industries=[],
                change_percent=Decimal('8'),
                turnover=Decimal('800000000'),
                published_at=self.published_at,
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
        # 版本概念已删除：信封里不再有 data_version。结果按业务日期唯一，缓存身份
        # 留在服务内部，第二次请求命中缓存即证明它稳定。
        self.assertNotIn('data_version', first.json())
        self.assertEqual(first.json()['source'], 'database')
        # 六组计数由这一天的行算出来，不再是单独存的字段。
        self.assertEqual(
            first.json()['data']['group_counts'],
            {
                'sse_rise': 1, 'sse_fall': 0,
                'szse_rise': 1, 'szse_fall': 0,
                'bse_rise': 0, 'bse_fall': 0,
            },
        )
        # 顺序跟页面分组一致（上证上涨 → 深证上涨），不是字典序。
        self.assertEqual(first.json()['data']['stock_codes'], ['600001', '000001'])
        self.assertEqual(
            first.json()['data']['groups']['sse_rise'][0]['industries'],
            [{'code': 'I001', 'name': '银行'}],
        )
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()['source'], 'cache')
        self.assertEqual(second.json()['data'], first.json()['data'])

    @patch('stock_moves.services.read_path.default_file_cache')
    def test_warnings_are_rebuilt_from_the_rows_that_need_them(self, cache_factory):
        """告警不落库：名称缺失 / 行业为空这两条由行本身推出来。"""
        cache_factory.return_value = self.cache
        StockMoveItem.objects.using('stock_moves').create(
            business_date=self.trade_date,
            group=StockMoveItem.Group.BSE_RISE,
            rank=1,
            stock_code='920045',
            stock_name='',
            industries=[],
            change_percent=Decimal('9.81'),
            turnover=Decimal('1218000000'),
            published_at=self.published_at,
        )

        response = self._authenticated_client().get('/api/stock-moves/?date=2026-09-08')

        warnings = response.json()['warnings']
        self.assertIn('股票 920045 名称缺失。', warnings)
        self.assertIn('股票 920045 未映射到开盘啦板块。', warnings)
        self.assertIn('股票 000001 未映射到开盘啦板块。', warnings)

    @patch('stock_moves.services.read_path.default_file_cache')
    def test_bse_groups_are_returned_after_the_four_exchange_groups_and_copied_too(
        self, cache_factory
    ):
        cache_factory.return_value = self.cache
        StockMoveItem.objects.using('stock_moves').bulk_create([
            StockMoveItem(
                business_date=self.trade_date,
                group=StockMoveItem.Group.BSE_RISE,
                rank=1,
                stock_code='920045',
                stock_name='蘅东光',
                industries=[{'code': 'I007', 'name': '通信'}],
                change_percent=Decimal('9.81'),
                turnover=Decimal('1218000000'),
                published_at=self.published_at,
            ),
            StockMoveItem(
                business_date=self.trade_date,
                group=StockMoveItem.Group.BSE_FALL,
                rank=1,
                stock_code='920046',
                stock_name='蘅西光',
                industries=[],
                change_percent=Decimal('-8.42'),
                turnover=Decimal('900000000'),
                published_at=self.published_at,
            ),
        ])

        response = self._authenticated_client().get('/api/stock-moves/?date=2026-09-08')

        self.assertEqual(response.status_code, 200)
        data = response.json()['data']
        self.assertEqual(data['group_counts']['bse_rise'], 1)
        self.assertEqual(data['group_counts']['bse_fall'], 1)
        self.assertEqual(
            [(item['code'], item['name']) for item in data['groups']['bse_rise']],
            [('920045', '蘅东光')],
        )
        self.assertEqual(
            [(item['code'], item['name']) for item in data['groups']['bse_fall']],
            [('920046', '蘅西光')],
        )
        self.assertEqual(data['distinct_stock_count'], 4)
        # 北交所股票计入「全部复制」，且追加在四组之后（先涨后跌）。
        self.assertEqual(data['stock_codes'], ['600001', '000001', '920045', '920046'])

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
        StockMoveItem.objects.using('stock_moves').create(
            business_date=date(2026, 9, 7),
            group=StockMoveItem.Group.SSE_RISE,
            rank=1,
            stock_code='600009',
            stock_name='前一天',
            industries=[],
            change_percent=Decimal('9'),
            turnover=Decimal('900000000'),
            published_at=self.published_at,
        )

        response = self._authenticated_client().get('/api/stock-moves/dates/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['dates'], ['2026-09-08', '2026-09-07'])
        self.assertEqual(response.json()['source'], 'database')
