from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from backend.db_router import AppDatabaseRouter
from sector_momentum.models import SectorMomentumRanking


class SectorMomentumModelTests(TestCase):
    databases = {'default', 'sector_momentum'}

    def _ranking(self, **overrides):
        values = {
            'business_date': date(2026, 9, 8),
            'metric': SectorMomentumRanking.Metric.ABOVE_5PCT,
            'industry_code': 'I001',
            'industry_name': '银行',
            'stocks': [
                {
                    'code': '600000',
                    'name': '浦发银行',
                    'change_percent': '8.000000',
                    'turnover': '50000000.0000',
                }
            ],
            'total_market_turnover': Decimal('1000000000'),
            'unmapped_stock_count': 2,
            'published_at': timezone.now(),
        }
        values.update(overrides)
        return SectorMomentumRanking(**values)

    def test_one_table_carries_the_day_the_industry_and_its_stocks(self):
        """单表：业务日期与两个日级事实都在排行行上，没有单独的结果表。"""
        ranking = self._ranking()
        ranking.save(using='sector_momentum')

        self.assertEqual(ranking.business_date, date(2026, 9, 8))
        self.assertEqual(ranking.metric, SectorMomentumRanking.Metric.ABOVE_5PCT)
        self.assertEqual(ranking.stocks[0]['code'], '600000')
        self.assertEqual(ranking.total_market_turnover, Decimal('1000000000'))
        self.assertEqual(ranking.unmapped_stock_count, 2)
        self.assertFalse(hasattr(ranking, 'result_id'))

    def test_derived_numbers_are_no_longer_columns(self):
        """名次与五个数值列都是 ``stocks`` 的函数，不再是字段。"""
        for name in (
            'rank',
            'stock_count',
            'average_change_percent',
            'industry_turnover',
            'market_turnover_ratio',
            'score',
        ):
            self.assertFalse(
                hasattr(SectorMomentumRanking, name),
                f'{name} 应该由 stocks 现算，不该是列',
            )

    def test_a_metric_holds_an_industry_at_most_once_per_business_date(self):
        """唯一性按（天, 口径, 行业）：名次不落库，所以它不再是键的一部分。"""
        self._ranking().save(using='sector_momentum')
        self._ranking(
            metric=SectorMomentumRanking.Metric.TOP_5_PERCENT
        ).save(using='sector_momentum')
        self._ranking(
            business_date=date(2026, 9, 9)
        ).save(using='sector_momentum')

        with self.assertRaises(IntegrityError), transaction.atomic():
            self._ranking().save(using='sector_momentum')

    def test_ranking_rejects_unknown_metric(self):
        invalid = self._ranking(metric='unknown')

        with self.assertRaises(ValidationError):
            invalid.full_clean()

    def test_models_route_to_own_database_without_cross_database_foreign_keys(self):
        router = AppDatabaseRouter()
        self.assertEqual(router.db_for_read(SectorMomentumRanking), 'sector_momentum')
        self.assertEqual(router.db_for_write(SectorMomentumRanking), 'sector_momentum')

        for field in SectorMomentumRanking._meta.get_fields():
            if getattr(field, 'many_to_one', False) or getattr(field, 'one_to_one', False):
                self.assertEqual(field.related_model._meta.app_label, 'sector_momentum')
