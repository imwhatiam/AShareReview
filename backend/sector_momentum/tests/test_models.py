from datetime import date, datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from backend.db_router import AppDatabaseRouter
from sector_momentum.models import (
    SectorMomentumRanking,
    SectorMomentumResult,
    SectorMomentumRun,
)


class SectorMomentumModelTests(TestCase):
    databases = {'default', 'sector_momentum'}

    def _result(self):
        return SectorMomentumResult.objects.create(
            business_date=date(2026, 9, 8),
            source_daily_price_version='daily-prices-20260908-v1',
            source_industry_version='kaipanla-industries-v1',
            total_market_turnover=Decimal('1000000000'),
            unmapped_stock_count=2,
        )

    def test_result_keeps_public_data_and_industry_mapping_versions(self):
        result = self._result()

        self.assertEqual(result.business_date, date(2026, 9, 8))
        self.assertEqual(result.source_daily_price_version, 'daily-prices-20260908-v1')
        self.assertEqual(result.source_industry_version, 'kaipanla-industries-v1')
        self.assertEqual(result.total_market_turnover, Decimal('1000000000'))
        self.assertEqual(result.unmapped_stock_count, 2)

    def test_ranking_keeps_supported_metric_stock_detail_and_score_components(self):
        ranking = SectorMomentumRanking.objects.create(
            result=self._result(),
            metric=SectorMomentumRanking.Metric.ABOVE_5PCT,
            rank=1,
            industry_code='I001',
            industry_name='银行',
            stock_count=2,
            average_change_percent=Decimal('7.500000'),
            industry_turnover=Decimal('100000000'),
            market_turnover_ratio=Decimal('0.10000000'),
            score=Decimal('1.500000000000'),
            stocks=[
                {
                    'code': '600000',
                    'name': '浦发银行',
                    'change_percent': '8.000000',
                    'turnover': '50000000.0000',
                }
            ],
        )

        self.assertEqual(ranking.metric, SectorMomentumRanking.Metric.ABOVE_5PCT)
        self.assertEqual(ranking.stocks[0]['code'], '600000')
        self.assertEqual(ranking.score, Decimal('1.500000000000'))

    def test_ranking_rejects_unknown_metric_and_duplicate_metric_rank(self):
        result = self._result()
        SectorMomentumRanking.objects.create(
            result=result,
            metric=SectorMomentumRanking.Metric.TOP_5_PERCENT,
            rank=1,
            industry_code='I001',
            industry_name='银行',
        )
        invalid = SectorMomentumRanking(
            result=result,
            metric='unknown',
            rank=2,
            industry_code='I002',
            industry_name='券商',
        )

        with self.assertRaises(ValidationError):
            invalid.full_clean()
        with self.assertRaises(IntegrityError), transaction.atomic():
            SectorMomentumRanking.objects.create(
                result=result,
                metric=SectorMomentumRanking.Metric.TOP_5_PERCENT,
                rank=1,
                industry_code='I002',
                industry_name='券商',
            )

    def test_run_keeps_independent_execution_record(self):
        run = SectorMomentumRun.objects.create(
            source_batch_id='sector-momentum-20260908-001',
            business_date=date(2026, 9, 8),
            status=SectorMomentumRun.Status.SUCCESS,
            source_daily_price_version='daily-prices-20260908-v1',
            source_industry_version='kaipanla-industries-v1',
            total_market_turnover=Decimal('1000000000'),
            unmapped_stock_count=2,
            started_at=timezone.make_aware(datetime(2026, 9, 8, 15, 1)),
            finished_at=timezone.make_aware(datetime(2026, 9, 8, 15, 2)),
        )

        self.assertEqual(run.status, SectorMomentumRun.Status.SUCCESS)
        self.assertEqual(run.unmapped_stock_count, 2)

    def test_models_route_to_own_database_without_cross_database_foreign_keys(self):
        router = AppDatabaseRouter()
        self.assertEqual(router.db_for_read(SectorMomentumResult), 'sector_momentum')
        self.assertEqual(router.db_for_write(SectorMomentumRun), 'sector_momentum')

        for model in (SectorMomentumResult, SectorMomentumRanking, SectorMomentumRun):
            for field in model._meta.get_fields():
                if getattr(field, 'many_to_one', False) or getattr(field, 'one_to_one', False):
                    self.assertEqual(field.related_model._meta.app_label, 'sector_momentum')
