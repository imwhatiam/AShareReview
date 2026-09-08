from datetime import date
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase


class DatasetModelTests(TestCase):
    def setUp(self):
        from core.models import Stock

        self.stock = Stock.objects.create(
            thscode='000001.SZ',
            stock_code='000001',
            stock_name='平安银行',
            exchange=Stock.Exchange.SZSE,
        )

    def test_daily_price_is_unique_per_stock_and_trade_date(self):
        from core.models import DailyPrice

        values = {
            'stock': self.stock,
            'trade_date': date(2026, 9, 8),
            'pre_close': Decimal('10.00'),
            'open_price': Decimal('10.10'),
            'high_price': Decimal('10.30'),
            'low_price': Decimal('9.90'),
            'close_price': Decimal('10.20'),
            'change_percent': Decimal('2.00'),
            'volume': 1000,
            'turnover': Decimal('10200.00'),
            'has_valid_trade': True,
            'source_batch_id': 'batch-20260908',
            'source_data_version': 'prices-20260908-v1',
        }
        DailyPrice.objects.create(**values)

        with self.assertRaises(IntegrityError), transaction.atomic():
            DailyPrice.objects.create(**values)

    def test_data_version_distinguishes_complete_partial_and_failed(self):
        from core.models import DataVersion

        complete = DataVersion.objects.create(
            dataset_key='stock_daily_prices',
            version='prices-20260908-v1',
            business_date=date(2026, 9, 8),
            status=DataVersion.Status.COMPLETE,
            expected_record_count=10,
            actual_record_count=10,
            missing_record_count=0,
        )
        partial = DataVersion.objects.create(
            dataset_key='stock_daily_prices',
            version='prices-20260908-v2',
            business_date=date(2026, 9, 8),
            status=DataVersion.Status.PARTIAL,
            expected_record_count=10,
            actual_record_count=9,
            missing_record_count=1,
        )
        failed = DataVersion.objects.create(
            dataset_key='stock_daily_prices',
            version='prices-20260908-v3',
            business_date=date(2026, 9, 8),
            status=DataVersion.Status.FAILED,
            expected_record_count=10,
            actual_record_count=0,
            missing_record_count=10,
            error_summary='upstream unavailable',
        )

        self.assertEqual(
            {complete.status, partial.status, failed.status},
            {
                DataVersion.Status.COMPLETE,
                DataVersion.Status.PARTIAL,
                DataVersion.Status.FAILED,
            },
        )

    def test_run_status_keeps_a_removed_module_identifier_without_relation(self):
        from core.models import ModuleRunStatus

        status = ModuleRunStatus.objects.create(
            module_id='removed_module',
            dataset_key='daily_analysis',
            status=ModuleRunStatus.Status.FAILED,
            business_date=date(2026, 9, 8),
            source_data_version='prices-20260908-v1',
            serving_stale=True,
            consecutive_failure_count=2,
            error_summary='last failure',
        )

        self.assertEqual(status.module_id, 'removed_module')
        self.assertFalse(
            any(field.is_relation for field in ModuleRunStatus._meta.fields)
        )
