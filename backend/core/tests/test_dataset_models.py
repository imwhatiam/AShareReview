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

    def test_data_version_round_trips_every_status_and_orders_newest_first(self):
        """真存真读一遍状态列，并钉住"最新在前"的默认排序。

        这一条以前是"造四个对象，再断言传入的 status 集合 == 枚举集合"——两边同
        源，恒真、零覆盖。真正值得守的是两件会被静默破坏的事：

        1. ``status`` 列是 ``max_length=8``，而 ``complete`` 正好 8 个字符：再加长
           或改名就会被数据库静默截断成 ``complete`` 之外的值。
        2. 读路径用 ``.first()`` / ``.order_by('-last_success_at')`` 取最新版本，
           ``Meta.ordering`` 是它没写 order_by 时的兜底 —— 反了就会一直读到旧版本。
        """
        from datetime import timedelta

        from django.utils import timezone

        from core.models import DataVersion

        base = timezone.now()
        for index, status in enumerate(DataVersion.Status.values):
            version = DataVersion.objects.create(
                dataset_key='stock_daily_prices',
                version=f'prices-20260908-v{index}',
                business_date=date(2026, 9, 8),
                status=status,
                expected_record_count=10,
                actual_record_count=10,
                error_summary=f'状态 {status} 的备注',
                started_at=base + timedelta(seconds=index),
            )
            version.refresh_from_db()
            self.assertEqual(version.status, status)
            self.assertEqual(version.error_summary, f'状态 {status} 的备注')

        self.assertEqual(
            [row.status for row in DataVersion.objects.all()],
            list(reversed(DataVersion.Status.values)),
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
