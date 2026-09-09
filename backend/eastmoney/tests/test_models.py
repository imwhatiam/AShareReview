from datetime import date, datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, router, transaction
from django.test import TestCase
from django.utils import timezone

from eastmoney.models import (
    EastmoneySectorFundFlowRun,
    EastmoneySectorFundFlowSnapshot,
)


class EastmoneyModelTests(TestCase):
    databases = {'default', 'eastmoney'}

    def test_snapshot_keeps_upstream_amounts_and_is_unique_per_sector_and_time(self):
        snapshot_time = timezone.make_aware(datetime(2026, 9, 9, 10, 0))
        snapshot = EastmoneySectorFundFlowSnapshot.objects.create(
            sector_code='BK0475',
            sector_name='半导体',
            trade_date=date(2026, 9, 9),
            snapshot_time=snapshot_time,
            latest_index=Decimal('4321.123'),
            change_pct=Decimal('1.234'),
            main_net_inflow=Decimal('1200000.50'),
            main_net_inflow_ratio=Decimal('3.210'),
            super_large_net_inflow=Decimal('700000.00'),
            large_net_inflow=Decimal('300000.00'),
            medium_net_inflow=Decimal('150000.00'),
            small_net_inflow=Decimal('-50000.00'),
            source_batch_id='eastmoney-batch-1',
        )

        self.assertEqual(snapshot.main_net_inflow, Decimal('1200000.50'))
        self.assertEqual(snapshot.latest_index, Decimal('4321.123'))

        with self.assertRaises(IntegrityError), transaction.atomic():
            EastmoneySectorFundFlowSnapshot.objects.create(
                sector_code='BK0475',
                sector_name='重复板块',
                trade_date=date(2026, 9, 9),
                snapshot_time=snapshot_time,
                main_net_inflow=Decimal('1.00'),
                source_batch_id='eastmoney-batch-2',
            )

    def test_run_records_inflow_and_outflow_independently_for_partial_result(self):
        run = EastmoneySectorFundFlowRun.objects.create(
            source_batch_id='eastmoney-run-partial',
            trade_date=date(2026, 9, 9),
            snapshot_time=timezone.make_aware(datetime(2026, 9, 9, 10, 0)),
            status=EastmoneySectorFundFlowRun.Status.PARTIAL,
            inflow_status=EastmoneySectorFundFlowRun.DirectionStatus.COMPLETE,
            outflow_status=EastmoneySectorFundFlowRun.DirectionStatus.FAILED,
            inflow_record_count=50,
            outflow_record_count=0,
            outflow_error_summary='HTTP 403 blocked by upstream.',
        )

        self.assertEqual(run.status, EastmoneySectorFundFlowRun.Status.PARTIAL)
        self.assertEqual(run.inflow_status, EastmoneySectorFundFlowRun.DirectionStatus.COMPLETE)
        self.assertEqual(run.outflow_status, EastmoneySectorFundFlowRun.DirectionStatus.FAILED)

    def test_run_rejects_complete_when_either_direction_failed(self):
        run = EastmoneySectorFundFlowRun(
            source_batch_id='eastmoney-run-invalid',
            trade_date=date(2026, 9, 9),
            snapshot_time=timezone.make_aware(datetime(2026, 9, 9, 10, 0)),
            status=EastmoneySectorFundFlowRun.Status.COMPLETE,
            inflow_status=EastmoneySectorFundFlowRun.DirectionStatus.COMPLETE,
            outflow_status=EastmoneySectorFundFlowRun.DirectionStatus.FAILED,
        )

        with self.assertRaises(ValidationError):
            run.full_clean()

    def test_run_records_double_upstream_failure_without_complete_status(self):
        run = EastmoneySectorFundFlowRun.objects.create(
            source_batch_id='eastmoney-run-failed',
            trade_date=date(2026, 9, 9),
            snapshot_time=timezone.make_aware(datetime(2026, 9, 9, 10, 0)),
            status=EastmoneySectorFundFlowRun.Status.FAILED,
            inflow_status=EastmoneySectorFundFlowRun.DirectionStatus.FAILED,
            outflow_status=EastmoneySectorFundFlowRun.DirectionStatus.FAILED,
            inflow_error_summary='HTTP 403 blocked by upstream.',
            outflow_error_summary='HTTP 403 blocked by upstream.',
        )

        self.assertEqual(run.status, EastmoneySectorFundFlowRun.Status.FAILED)
        self.assertNotEqual(run.status, EastmoneySectorFundFlowRun.Status.COMPLETE)

    def test_eastmoney_models_route_to_their_own_database(self):
        self.assertEqual(router.db_for_read(EastmoneySectorFundFlowSnapshot), 'eastmoney')
        self.assertEqual(router.db_for_write(EastmoneySectorFundFlowRun), 'eastmoney')

    def test_eastmoney_models_have_no_cross_database_foreign_keys(self):
        for model in (EastmoneySectorFundFlowSnapshot, EastmoneySectorFundFlowRun):
            foreign_keys = [
                field for field in model._meta.get_fields()
                if getattr(field, 'many_to_one', False) or getattr(field, 'one_to_one', False)
            ]
            self.assertEqual(foreign_keys, [])
