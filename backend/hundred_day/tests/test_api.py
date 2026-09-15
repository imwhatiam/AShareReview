from datetime import date
from decimal import Decimal
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from core.services.file_cache import FileCache
from hundred_day.models import (
    HundredDayBreadth,
    HundredDayIndustrySummary,
    HundredDayStockFlag,
)
from hundred_day.services.analysis import InsufficientHundredDayHistory


class HundredDayApiTests(TestCase):
    databases = {'default', 'hundred_day'}

    def setUp(self):
        self.trade_date = date(2026, 9, 8)
        self.user = get_user_model().objects.create_user(
            username='hundred-day-user', password='correct-password'
        )
        # 业务日期那一行同时就是"当日结果"，不再单独存一份汇总。
        HundredDayBreadth.objects.using('hundred_day').create(
            business_date=self.trade_date,
            trade_date=self.trade_date,
            valid_stock_count=2,
            new_high_count=1,
            new_low_count=1,
            published_at=timezone.now(),
        )
        HundredDayStockFlag.objects.using('hundred_day').create(
            business_date=self.trade_date,
            stock_code='600001',
            stock_name='测试股票',
            industries=[{'code': 'I001', 'name': '电子'}],
            is_new_high=True,
            change_percent=Decimal('10.000000'),
            turnover=Decimal('123456789.0000'),
        )
        # 行业汇总只落 stock_count；下面的 new_high_count / 名单都是读时算的。
        HundredDayIndustrySummary.objects.using('hundred_day').create(
            business_date=self.trade_date,
            industry_code='I001',
            industry_name='电子',
            stock_count=1,
        )
        self.cache_directory = TemporaryDirectory()
        self.cache = FileCache(self.cache_directory.name, ttl_seconds=300, max_bytes=1_000_000)
        self.addCleanup(self.cache_directory.cleanup)

    def _authenticated_client(self):
        self.client.force_login(self.user)
        return self.client

    def test_endpoints_require_an_authenticated_session(self):
        response = self.client.get('/api/hundred-day/')

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['error']['code'], 'AUTH_REQUIRED')

    @patch('hundred_day.services.read_path.default_file_cache')
    def test_result_returns_structured_totals_industries_flags_and_trend(self, cache_factory):
        cache_factory.return_value = self.cache

        first = self._authenticated_client().get('/api/hundred-day/?date=2026-09-08')
        second = self._authenticated_client().get('/api/hundred-day/?date=2026-09-08')

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()['business_date'], '2026-09-08')
        self.assertEqual(first.json()['source'], 'database')
        self.assertEqual(first.json()['data']['totals'], {
            'valid_stock_count': 2,
            'new_high_count': 1,
            'new_low_count': 1,
            'new_high_ratio': '0.5',
            'new_low_ratio': '0.5',
        })
        self.assertEqual(first.json()['data']['industry_summaries'][0]['industry_code'], 'I001')
        self.assertEqual(
            first.json()['data']['industry_summaries'][0]['new_high_stocks'],
            [{
                'code': '600001', 'name': '测试股票',
                'change_percent': '10.000000', 'turnover': '123456789.0000',
            }],
        )
        self.assertEqual(first.json()['data']['industry_summaries'][0]['new_low_stocks'], [])
        self.assertEqual(first.json()['data']['stock_flags'][0]['code'], '600001')
        self.assertEqual(first.json()['data']['trend'][0]['new_high_ratio'], '0.50000000')
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()['source'], 'cache')
        self.assertEqual(second.json()['data'], first.json()['data'])

    @patch('hundred_day.services.read_path.default_file_cache')
    def test_industry_counts_are_derived_from_the_same_grouping_as_the_lists(self, cache_factory):
        """行业新高/新低数量不是列，而是与名单同一次分组的 ``len()``。

        成分股 5 只、被标记 1 只：``stock_count`` 是落库的行业事实，两个计数必须是
        1 和 0，与名单长度逐一致 —— 它们不可能互相矛盾。
        """
        cache_factory.return_value = self.cache
        HundredDayIndustrySummary.objects.using('hundred_day').filter(
            business_date=self.trade_date, industry_code='I001'
        ).update(stock_count=5)

        response = self._authenticated_client().get('/api/hundred-day/?date=2026-09-08')

        summary = response.json()['data']['industry_summaries'][0]
        self.assertEqual(summary['stock_count'], 5)
        self.assertEqual(summary['new_high_count'], 1)
        self.assertEqual(summary['new_low_count'], 0)
        self.assertEqual(len(summary['new_high_stocks']), summary['new_high_count'])
        self.assertEqual(len(summary['new_low_stocks']), summary['new_low_count'])

    @patch('hundred_day.services.read_path.default_file_cache')
    def test_industry_stock_lists_are_rebuilt_from_flags_in_stock_code_order(self, cache_factory):
        """行业名单不落库：读时按 industries 分组重建，跨行业股票出现在每个行业里。"""
        cache_factory.return_value = self.cache
        earlier = date(2026, 9, 7)
        HundredDayBreadth.objects.using('hundred_day').create(
            business_date=earlier,
            trade_date=earlier,
            valid_stock_count=2,
            new_high_count=2,
            published_at=timezone.now(),
        )
        for stock_code, industries in (
            ('600003', [{'code': 'I002', 'name': '半导体'}]),
            (
                '600001',
                [{'code': 'I001', 'name': '电子'}, {'code': 'I002', 'name': '半导体'}],
            ),
        ):
            HundredDayStockFlag.objects.using('hundred_day').create(
                business_date=earlier,
                stock_code=stock_code,
                stock_name=f'股票{stock_code}',
                industries=industries,
                is_new_high=True,
                change_percent=Decimal('1.500000'),
                turnover=Decimal('100.0000'),
            )
        for industry_code, industry_name in (('I001', '电子'), ('I002', '半导体')):
            HundredDayIndustrySummary.objects.using('hundred_day').create(
                business_date=earlier,
                industry_code=industry_code,
                industry_name=industry_name,
                stock_count=2,
            )

        response = self._authenticated_client().get('/api/hundred-day/?date=2026-09-07')

        self.assertEqual(response.status_code, 200)
        summaries = {
            item['industry_code']: item
            for item in response.json()['data']['industry_summaries']
        }
        self.assertEqual(
            [stock['code'] for stock in summaries['I001']['new_high_stocks']], ['600001']
        )
        self.assertEqual(
            [stock['code'] for stock in summaries['I002']['new_high_stocks']],
            ['600001', '600003'],
        )
        self.assertEqual(summaries['I002']['new_low_stocks'], [])
        self.assertEqual(summaries['I002']['new_high_count'], 2)

    def test_explicit_invalid_or_unavailable_dates_do_not_silently_fallback(self):
        client = self._authenticated_client()

        malformed = client.get('/api/hundred-day/?date=2026-9-8')
        unavailable = client.get('/api/hundred-day/?date=2026-09-07')

        self.assertEqual(malformed.status_code, 400)
        self.assertEqual(malformed.json()['error']['code'], 'INVALID_DATE')
        self.assertEqual(unavailable.status_code, 404)
        self.assertEqual(unavailable.json()['error']['code'], 'DATA_NOT_AVAILABLE')

    @patch(
        'hundred_day.views.read_hundred_day',
        side_effect=InsufficientHundredDayHistory('需要 199 个交易日的行情。'),
    )
    def test_insufficient_history_is_404_for_an_explicit_date_and_202_by_default(self, read):
        """历史不足对历史日期永远不会自愈：202 只会让前端一直重试。"""
        client = self._authenticated_client()

        explicit = client.get('/api/hundred-day/?date=2026-09-08')
        default = client.get('/api/hundred-day/')

        self.assertEqual(explicit.status_code, 404)
        self.assertEqual(explicit.json()['error']['code'], 'INSUFFICIENT_HISTORY')
        self.assertEqual(default.status_code, 202)
        self.assertEqual(default.json()['error']['code'], 'INSUFFICIENT_HISTORY')
        self.assertEqual(default.json()['preparation']['state'], 'insufficient_history')

    @patch('hundred_day.services.read_path.default_file_cache')
    def test_dates_lists_distinct_available_result_dates(self, cache_factory):
        """一个业务日期现在有很多个宽度点，但日期列表里它只能出现一次。"""
        cache_factory.return_value = self.cache
        earlier = date(2026, 9, 7)
        for trade_date in (date(2026, 9, 3), date(2026, 9, 4), earlier):
            HundredDayBreadth.objects.using('hundred_day').create(
                business_date=earlier,
                trade_date=trade_date,
                published_at=timezone.now(),
            )

        response = self._authenticated_client().get('/api/hundred-day/dates/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['dates'], ['2026-09-08', '2026-09-07'])
