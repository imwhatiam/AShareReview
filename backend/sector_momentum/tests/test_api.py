from datetime import date
from decimal import Decimal
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from core.services.file_cache import FileCache
from sector_momentum.models import SectorMomentumRanking


class SectorMomentumApiTests(TestCase):
    databases = {'default', 'sector_momentum'}

    def setUp(self):
        self.trade_date = date(2026, 9, 8)
        self.user = get_user_model().objects.create_user(
            username='sector-momentum-user', password='correct-password'
        )
        self.published_at = timezone.now()
        SectorMomentumRanking.objects.using('sector_momentum').create(
            business_date=self.trade_date,
            metric=SectorMomentumRanking.Metric.ABOVE_5PCT,
            industry_code='I001',
            industry_name='银行',
            stocks=[{
                'code': '600001', 'name': '上涨股票',
                'change_percent': '8', 'turnover': '100000000',
            }],
            total_market_turnover=Decimal('1000000000'),
            unmapped_stock_count=1,
            published_at=self.published_at,
        )
        self.cache_directory = TemporaryDirectory()
        self.cache = FileCache(self.cache_directory.name, ttl_seconds=300, max_bytes=1_000_000)
        self.addCleanup(self.cache_directory.cleanup)

    def _authenticated_client(self):
        self.client.force_login(self.user)
        return self.client

    def test_endpoints_require_an_authenticated_session(self):
        response = self.client.get('/api/sector-momentum/')

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['error']['code'], 'AUTH_REQUIRED')

    @patch('sector_momentum.services.read_path.default_file_cache')
    def test_result_returns_both_metrics_stock_details_and_unmapped_warning(self, cache_factory):
        cache_factory.return_value = self.cache

        first = self._authenticated_client().get('/api/sector-momentum/?date=2026-09-08')
        second = self._authenticated_client().get('/api/sector-momentum/?date=2026-09-08')

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()['status'], 'partial')
        self.assertEqual(first.json()['business_date'], '2026-09-08')
        self.assertEqual(first.json()['source'], 'database')
        self.assertEqual(first.json()['data']['total_market_turnover'], '1000000000.0000')
        self.assertEqual(first.json()['data']['unmapped_stock_count'], 1)
        self.assertEqual(
            first.json()['data']['rankings']['above_5pct'][0]['stocks'][0]['code'], '600001'
        )
        self.assertEqual(first.json()['data']['rankings']['top_5_percent'], [])
        self.assertIn('1 只有效股票未映射到开盘啦板块。', first.json()['warnings'])
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()['source'], 'cache')
        self.assertEqual(second.json()['data'], first.json()['data'])

    @patch('sector_momentum.services.read_path.default_file_cache')
    def test_the_five_numbers_and_the_rank_are_recomputed_from_the_stock_detail(
        self, cache_factory
    ):
        """名次与五个数值列不落库：报文里的值由 stocks 加全市场成交额现算。"""
        cache_factory.return_value = self.cache
        SectorMomentumRanking.objects.using('sector_momentum').create(
            business_date=self.trade_date,
            metric=SectorMomentumRanking.Metric.ABOVE_5PCT,
            industry_code='I002',
            industry_name='券商',
            stocks=[
                {
                    'code': '600002', 'name': '甲',
                    'change_percent': '9', 'turnover': '200000000',
                },
                {
                    'code': '600003', 'name': '乙',
                    'change_percent': '7', 'turnover': '100000000',
                },
            ],
            total_market_turnover=Decimal('1000000000'),
            unmapped_stock_count=1,
            published_at=self.published_at,
        )

        response = self._authenticated_client().get('/api/sector-momentum/?date=2026-09-08')

        rankings = response.json()['data']['rankings']['above_5pct']
        by_code = {item['industry_code']: item for item in rankings}
        self.assertEqual(
            {item['industry_code']: item['rank'] for item in rankings},
            {'I002': 1, 'I001': 2},
            '名次按综合评分降序：I002 的 2 只股票评分更高',
        )
        self.assertEqual(by_code['I002']['stock_count'], 2)
        self.assertEqual(by_code['I002']['industry_turnover'], '300000000.0000')
        self.assertEqual(by_code['I002']['average_change_percent'], '8.000000')
        self.assertEqual(by_code['I002']['market_turnover_ratio'], '0.30000000')
        self.assertEqual(by_code['I002']['score'], '4.800000000000')
        self.assertEqual(by_code['I001']['stock_count'], 1)
        self.assertEqual(by_code['I001']['score'], '0.800000000000')

    def test_explicit_invalid_or_unavailable_dates_are_rejected_without_silent_fallback(self):
        client = self._authenticated_client()

        malformed = client.get('/api/sector-momentum/?date=2026-9-8')
        unavailable = client.get('/api/sector-momentum/?date=2026-09-07')

        self.assertEqual(malformed.status_code, 400)
        self.assertEqual(malformed.json()['error']['code'], 'INVALID_DATE')
        self.assertEqual(unavailable.status_code, 404)
        self.assertEqual(unavailable.json()['error']['code'], 'DATA_NOT_AVAILABLE')

    @patch('sector_momentum.services.read_path.default_file_cache')
    def test_dates_lists_distinct_available_result_dates(self, cache_factory):
        cache_factory.return_value = self.cache
        SectorMomentumRanking.objects.using('sector_momentum').create(
            business_date=date(2026, 9, 7),
            metric=SectorMomentumRanking.Metric.ABOVE_5PCT,
            industry_code='I001',
            industry_name='银行',
            stocks=[],
            total_market_turnover=Decimal('1000000000'),
            published_at=self.published_at,
        )

        response = self._authenticated_client().get('/api/sector-momentum/dates/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['dates'], ['2026-09-08', '2026-09-07'])
        self.assertEqual(response.json()['source'], 'database')
