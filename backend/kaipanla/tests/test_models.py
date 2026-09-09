from datetime import date, datetime
from decimal import Decimal

from django.db import IntegrityError, router, transaction
from django.test import TestCase
from django.utils import timezone

from kaipanla.models import (
    KaipanlaSectorFundFlowRun,
    KaipanlaSectorFundFlowSnapshot,
)


class KaipanlaModelTests(TestCase):
    databases = {'default', 'kaipanla'}

    def test_snapshot_keeps_upstream_amounts_and_is_unique_per_sector_and_time(self):
        snapshot_time = timezone.make_aware(datetime(2026, 9, 8, 10, 5))
        snapshot = KaipanlaSectorFundFlowSnapshot.objects.create(
            sector_code='BK001',
            sector_name='半导体',
            trade_date=date(2026, 9, 8),
            snapshot_time=snapshot_time,
            change_pct=Decimal('1.234'),
            main_net_inflow=Decimal('1200000.50'),
            main_buy=Decimal('2100000.00'),
            main_sell=Decimal('899999.50'),
            large_order_net_inflow=Decimal('500000.25'),
            volume_ratio=Decimal('2.100'),
            turnover_amount=Decimal('9000000.00'),
            float_market_cap=Decimal('100000000.00'),
            total_market_cap=Decimal('150000000.00'),
            source_batch_id='batch-1',
        )

        self.assertEqual(snapshot.snapshot_time, snapshot_time)
        self.assertEqual(snapshot.main_net_inflow, Decimal('1200000.50'))
        self.assertEqual(snapshot.turnover_amount, Decimal('9000000.00'))

        with self.assertRaises(IntegrityError), transaction.atomic():
            KaipanlaSectorFundFlowSnapshot.objects.create(
                sector_code='BK001',
                sector_name='重复板块',
                trade_date=date(2026, 9, 8),
                snapshot_time=snapshot_time,
                main_net_inflow=Decimal('1.00'),
                source_batch_id='batch-2',
            )

    def test_run_records_required_page_completeness_and_failure_details(self):
        run = KaipanlaSectorFundFlowRun.objects.create(
            source_batch_id='run-1',
            trade_date=date(2026, 9, 8),
            snapshot_time=timezone.make_aware(datetime(2026, 9, 8, 10, 5)),
            status=KaipanlaSectorFundFlowRun.Status.FAILED,
            expected_page_count=3,
            completed_page_count=2,
            expected_record_count=240,
            actual_record_count=160,
            missing_record_count=80,
            failed_page_offsets=[160],
            error_summary='Page 160 timed out.',
        )

        self.assertEqual(run.failed_page_offsets, [160])
        self.assertEqual(run.missing_record_count, 80)
        self.assertEqual(run.status, KaipanlaSectorFundFlowRun.Status.FAILED)

    def test_kaipanla_models_route_to_their_own_database(self):
        self.assertEqual(router.db_for_read(KaipanlaSectorFundFlowSnapshot), 'kaipanla')
        self.assertEqual(router.db_for_write(KaipanlaSectorFundFlowRun), 'kaipanla')

    def test_kaipanla_models_have_no_cross_database_foreign_keys(self):
        for model in (KaipanlaSectorFundFlowSnapshot, KaipanlaSectorFundFlowRun):
            foreign_keys = [
                field for field in model._meta.get_fields()
                if getattr(field, 'many_to_one', False) or getattr(field, 'one_to_one', False)
            ]
            self.assertEqual(foreign_keys, [])
