from datetime import date, datetime

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from backend.db_router import AppDatabaseRouter
from hundred_day.models import (
    HundredDayIndustrySummary,
    HundredDayResult,
    HundredDayRun,
    HundredDayStockFlag,
    HundredDayTrend,
)


class HundredDayModelTests(TestCase):
    databases = {'default', 'hundred_day'}

    def _result(self):
        return HundredDayResult.objects.create(
            business_date=date(2026, 9, 8),
            source_daily_price_version='daily-prices-20260908-v1',
            source_industry_version='industries-v1',
            valid_stock_count=100,
            new_high_count=12,
            new_low_count=8,
        )

    def test_result_keeps_versions_and_market_level_counts(self):
        result = self._result()

        self.assertEqual(result.valid_stock_count, 100)
        self.assertEqual(result.new_high_count, 12)
        self.assertEqual(result.new_low_count, 8)
        self.assertEqual(result.source_industry_version, 'industries-v1')

    def test_stock_flag_is_unique_per_date_result_and_keeps_parent_industries(self):
        result = self._result()
        flag = HundredDayStockFlag.objects.create(
            result=result,
            stock_code='600000',
            stock_name='浦发银行',
            parent_industries=[{'code': 'I001', 'name': '银行'}],
            is_new_high=True,
            is_new_low=False,
        )

        self.assertTrue(flag.is_new_high)
        self.assertEqual(flag.parent_industries, [{'code': 'I001', 'name': '银行'}])
        with self.assertRaises(IntegrityError), transaction.atomic():
            HundredDayStockFlag.objects.create(
                result=result,
                stock_code='600000',
                stock_name='重复股票',
            )

    def test_industry_summary_keeps_counts_and_structured_high_low_stock_details(self):
        summary = HundredDayIndustrySummary.objects.create(
            result=self._result(),
            industry_code='I001',
            industry_name='银行',
            stock_count=3,
            new_high_count=2,
            new_low_count=1,
            new_high_stocks=[{'code': '600000', 'name': '浦发银行'}],
            new_low_stocks=[{'code': '600001', 'name': '邯郸钢铁'}],
        )

        self.assertEqual(summary.new_high_stocks[0]['code'], '600000')
        self.assertEqual(summary.new_low_count, 1)

    def test_trend_keeps_nullable_ratios_when_no_valid_stock_exists(self):
        trend = HundredDayTrend.objects.create(
            result=self._result(),
            trade_date=date(2026, 9, 7),
            valid_stock_count=0,
            new_high_count=0,
            new_low_count=0,
            new_high_ratio=None,
            new_low_ratio=None,
        )

        self.assertIsNone(trend.new_high_ratio)
        self.assertIsNone(trend.new_low_ratio)

    def test_invalid_flag_relation_is_rejected_by_model_validation(self):
        flag = HundredDayStockFlag(
            result=self._result(),
            stock_code='600000',
            stock_name='浦发银行',
            is_new_high=False,
            is_new_low=False,
        )

        with self.assertRaises(ValidationError):
            flag.full_clean()

    def test_run_keeps_independent_execution_record(self):
        run = HundredDayRun.objects.create(
            source_batch_id='hundred-day-20260908-001',
            business_date=date(2026, 9, 8),
            status=HundredDayRun.Status.SUCCESS,
            source_daily_price_version='daily-prices-20260908-v1',
            source_industry_version='industries-v1',
            started_at=timezone.make_aware(datetime(2026, 9, 8, 15, 1)),
            finished_at=timezone.make_aware(datetime(2026, 9, 8, 15, 2)),
        )

        self.assertEqual(run.status, HundredDayRun.Status.SUCCESS)

    def test_models_route_to_own_database_without_cross_database_foreign_keys(self):
        router = AppDatabaseRouter()
        self.assertEqual(router.db_for_read(HundredDayResult), 'hundred_day')
        self.assertEqual(router.db_for_write(HundredDayRun), 'hundred_day')
        for model in (
            HundredDayResult, HundredDayStockFlag, HundredDayIndustrySummary,
            HundredDayTrend, HundredDayRun,
        ):
            for field in model._meta.get_fields():
                if getattr(field, 'many_to_one', False) or getattr(field, 'one_to_one', False):
                    self.assertEqual(field.related_model._meta.app_label, 'hundred_day')
