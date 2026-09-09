from datetime import date, datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, router, transaction
from django.test import TestCase
from django.utils import timezone

from stock_moves.models import StockMoveItem, StockMoveResult, StockMoveRun


class StockMoveModelTests(TestCase):
    databases = {'default', 'stock_moves'}

    def test_result_keeps_business_date_and_public_daily_price_version(self):
        result = StockMoveResult.objects.create(
            business_date=date(2026, 9, 8),
            source_daily_price_version='daily-prices-20260908-v1',
            sse_rise_count=2,
            sse_fall_count=1,
            szse_rise_count=3,
            szse_fall_count=4,
            distinct_stock_count=10,
        )

        self.assertEqual(result.business_date, date(2026, 9, 8))
        self.assertEqual(result.source_daily_price_version, 'daily-prices-20260908-v1')
        self.assertEqual(result.distinct_stock_count, 10)

    def test_item_keeps_one_of_four_groups_rank_and_parent_industry_snapshot(self):
        result = StockMoveResult.objects.create(
            business_date=date(2026, 9, 8),
            source_daily_price_version='daily-prices-20260908-v1',
        )
        item = StockMoveItem.objects.create(
            result=result,
            group=StockMoveItem.Group.SSE_RISE,
            rank=1,
            stock_code='600000',
            stock_name='浦发银行',
            parent_industries=[{'code': 'I001', 'name': '银行'}],
            change_percent=Decimal('8.000000'),
            turnover=Decimal('800000000.0000'),
        )

        self.assertEqual(item.group, StockMoveItem.Group.SSE_RISE)
        self.assertEqual(item.rank, 1)
        self.assertEqual(item.parent_industries, [{'code': 'I001', 'name': '银行'}])

        with self.assertRaises(IntegrityError), transaction.atomic():
            StockMoveItem.objects.create(
                result=result,
                group=StockMoveItem.Group.SSE_RISE,
                rank=1,
                stock_code='600001',
                stock_name='另一只股票',
                parent_industries=[],
                change_percent=Decimal('9.000000'),
                turnover=Decimal('900000000.0000'),
            )

    def test_item_rejects_unknown_group(self):
        result = StockMoveResult.objects.create(
            business_date=date(2026, 9, 8),
            source_daily_price_version='daily-prices-20260908-v1',
        )
        item = StockMoveItem(
            result=result,
            group='other',
            rank=1,
            stock_code='600000',
            stock_name='浦发银行',
            parent_industries=[],
            change_percent=Decimal('8.000000'),
            turnover=Decimal('800000000.0000'),
        )

        with self.assertRaises(ValidationError):
            item.full_clean()

    def test_run_keeps_independent_execution_record(self):
        run = StockMoveRun.objects.create(
            source_batch_id='stock-moves-20260908-001',
            business_date=date(2026, 9, 8),
            status=StockMoveRun.Status.SUCCESS,
            source_daily_price_version='daily-prices-20260908-v1',
            started_at=timezone.make_aware(datetime(2026, 9, 8, 15, 1)),
            finished_at=timezone.make_aware(datetime(2026, 9, 8, 15, 2)),
            total_candidate_count=10,
        )

        self.assertEqual(run.status, StockMoveRun.Status.SUCCESS)
        self.assertEqual(run.total_candidate_count, 10)

    def test_models_route_to_stock_moves_database_and_have_no_cross_database_foreign_keys(self):
        self.assertEqual(router.db_for_read(StockMoveResult), 'stock_moves')
        self.assertEqual(router.db_for_write(StockMoveRun), 'stock_moves')

        for model in (StockMoveResult, StockMoveItem, StockMoveRun):
            foreign_keys = [
                field for field in model._meta.get_fields()
                if (getattr(field, 'many_to_one', False) or getattr(field, 'one_to_one', False))
            ]
            for field in foreign_keys:
                self.assertEqual(field.related_model._meta.app_label, 'stock_moves')

    def test_result_persists_non_fatal_analysis_warnings_for_api_reads(self):
        result = StockMoveResult.objects.create(
            business_date=date(2026, 9, 8),
            source_daily_price_version='daily-prices-20260908-v1',
            warnings=['股票 600001 未映射到开盘啦父行业。'],
        )

        self.assertEqual(result.warnings, ['股票 600001 未映射到开盘啦父行业。'])
