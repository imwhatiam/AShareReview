from datetime import date
from decimal import Decimal
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from core.services.file_cache import FileCache
from hundred_day.models import (
    HundredDayIndustrySummary,
    HundredDayResult,
    HundredDayStockFlag,
    HundredDayTrend,
)


class HundredDayApiTests(TestCase):
    databases = {'default', 'hundred_day'}

    def setUp(self):
        self.trade_date = date(2026, 9, 8)
        self.user = get_user_model().objects.create_user(
            username='hundred-day-user', password='correct-password'
        )
        self.result = HundredDayResult.objects.using('hundred_day').create(
            business_date=self.trade_date,
            source_daily_price_version='daily-prices-v1',
            source_industry_version='industries-v1',
            valid_stock_count=2,
            new_high_count=1,
            new_low_count=1,
        )
        HundredDayStockFlag.objects.using('hundred_day').create(
            result=self.result,
            stock_code='600001',
            stock_name='测试股票',
            parent_industries=[{'code': 'I001', 'name': '电子'}],
            is_new_high=True,
        )
        HundredDayIndustrySummary.objects.using('hundred_day').create(
            result=self.result,
            industry_code='I001',
            industry_name='电子',
            stock_count=1,
            new_high_count=1,
            new_high_stocks=[{'code': '600001', 'name': '测试股票'}],
        )
        HundredDayTrend.objects.using('hundred_day').create(
            result=self.result,
            trade_date=self.trade_date,
            valid_stock_count=2,
            new_high_count=1,
            new_low_count=1,
            new_high_ratio=Decimal('0.5'),
            new_low_ratio=Decimal('0.5'),
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
        self.assertEqual(first.json()['data']['stock_flags'][0]['code'], '600001')
        self.assertEqual(first.json()['data']['trend'][0]['new_high_ratio'], '0.50000000')
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()['source'], 'cache')
        self.assertEqual(second.json()['data'], first.json()['data'])

    def test_explicit_invalid_or_unavailable_dates_do_not_silently_fallback(self):
        client = self._authenticated_client()

        malformed = client.get('/api/hundred-day/?date=2026-9-8')
        unavailable = client.get('/api/hundred-day/?date=2026-09-07')

        self.assertEqual(malformed.status_code, 400)
        self.assertEqual(malformed.json()['error']['code'], 'INVALID_DATE')
        self.assertEqual(unavailable.status_code, 404)
        self.assertEqual(unavailable.json()['error']['code'], 'DATA_NOT_AVAILABLE')

    @patch('hundred_day.services.read_path.default_file_cache')
    def test_dates_lists_distinct_available_result_dates(self, cache_factory):
        cache_factory.return_value = self.cache
        HundredDayResult.objects.using('hundred_day').create(
            business_date=date(2026, 9, 7),
            source_daily_price_version='daily-prices-v0',
            source_industry_version='industries-v1',
        )

        response = self._authenticated_client().get('/api/hundred-day/dates/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['dates'], ['2026-09-08', '2026-09-07'])
