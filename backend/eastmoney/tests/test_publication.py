from datetime import date, datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from eastmoney.models import EastmoneySectorFundFlowRun, EastmoneySectorFundFlowSnapshot
from eastmoney.services.fetcher import (
    EastmoneyDirectionFetchResult,
    EastmoneySectorFundFlowFetchResult,
)
from eastmoney.services.writer import (
    UnpublishableEastmoneySnapshot,
    record_unpublishable_snapshot,
    write_publishable_snapshot,
)


class EastmoneySnapshotPublicationTests(TestCase):
    databases = {'default', 'eastmoney'}

    def test_writer_persists_complete_run_and_snapshot(self):
        write_result = write_publishable_snapshot(
            fetch_result=_complete_result(),
            snapshot_time=_snapshot_time(),
            source_batch_id='eastmoney-complete',
        )

        run = EastmoneySectorFundFlowRun.objects.using('eastmoney').get()
        snapshot = EastmoneySectorFundFlowSnapshot.objects.using('eastmoney').get(sector_code='BK001')
        self.assertEqual(write_result.record_count, 2)
        self.assertEqual(write_result.status, EastmoneySectorFundFlowRun.Status.COMPLETE)
        self.assertEqual(run.inflow_status, EastmoneySectorFundFlowRun.DirectionStatus.COMPLETE)
        self.assertEqual(run.outflow_status, EastmoneySectorFundFlowRun.DirectionStatus.COMPLETE)
        self.assertEqual(snapshot.source_batch_id, 'eastmoney-complete')

    def test_writer_persists_partial_run_with_identifiable_missing_direction(self):
        write_result = write_publishable_snapshot(
            fetch_result=_partial_result(),
            snapshot_time=_snapshot_time(),
            source_batch_id='eastmoney-partial',
        )

        run = EastmoneySectorFundFlowRun.objects.using('eastmoney').get()
        self.assertEqual(write_result.status, EastmoneySectorFundFlowRun.Status.PARTIAL)
        self.assertEqual(run.status, EastmoneySectorFundFlowRun.Status.PARTIAL)
        self.assertEqual(run.inflow_status, EastmoneySectorFundFlowRun.DirectionStatus.COMPLETE)
        self.assertEqual(run.outflow_status, EastmoneySectorFundFlowRun.DirectionStatus.FAILED)
        self.assertIn('HTTP 403', run.outflow_error_summary)

    def test_double_failure_keeps_existing_snapshots_and_records_failed_run(self):
        EastmoneySectorFundFlowSnapshot.objects.using('eastmoney').create(
            sector_code='OLD',
            sector_name='旧数据',
            trade_date=date(2026, 9, 8),
            snapshot_time=timezone.make_aware(datetime(2026, 9, 8, 15, 0)),
            main_net_inflow=Decimal('1'),
            source_batch_id='old-batch',
        )

        with self.assertRaises(UnpublishableEastmoneySnapshot):
            write_publishable_snapshot(
                fetch_result=_failed_result(),
                snapshot_time=_snapshot_time(),
                source_batch_id='eastmoney-failed',
            )
        record_unpublishable_snapshot(
            fetch_result=_failed_result(),
            snapshot_time=_snapshot_time(),
            source_batch_id='eastmoney-failed',
        )

        run = EastmoneySectorFundFlowRun.objects.using('eastmoney').get(
            source_batch_id='eastmoney-failed'
        )
        self.assertEqual(EastmoneySectorFundFlowSnapshot.objects.using('eastmoney').count(), 1)
        self.assertEqual(run.status, EastmoneySectorFundFlowRun.Status.FAILED)
        self.assertIn('HTTP 403', run.error_summary)


def _snapshot_time():
    return timezone.make_aware(datetime(2026, 9, 9, 10, 0))


def _complete_result():
    inflow = EastmoneyDirectionFetchResult('inflow', (_row('BK001', '10'),), True)
    outflow = EastmoneyDirectionFetchResult('outflow', (_row('BK002', '-10'),), True)
    return EastmoneySectorFundFlowFetchResult(inflow.rows + outflow.rows, inflow, outflow)


def _partial_result():
    inflow = EastmoneyDirectionFetchResult('inflow', (_row('BK001', '10'),), True)
    outflow = EastmoneyDirectionFetchResult('outflow', (), False, 'HTTP 403 blocked by upstream.')
    return EastmoneySectorFundFlowFetchResult(inflow.rows, inflow, outflow)


def _failed_result():
    inflow = EastmoneyDirectionFetchResult('inflow', (), False, 'HTTP 403 blocked by upstream.')
    outflow = EastmoneyDirectionFetchResult('outflow', (), False, 'HTTP 403 blocked by upstream.')
    return EastmoneySectorFundFlowFetchResult((), inflow, outflow)


def _row(sector_code, main_net_inflow):
    return {
        'sector_code': sector_code,
        'sector_name': sector_code,
        'latest_index': Decimal('100'),
        'change_pct': Decimal('1'),
        'main_net_inflow': Decimal(main_net_inflow),
        'main_net_inflow_ratio': Decimal('1'),
        'super_large_net_inflow': Decimal('1'),
        'large_net_inflow': Decimal('1'),
        'medium_net_inflow': Decimal('1'),
        'small_net_inflow': Decimal('1'),
    }
