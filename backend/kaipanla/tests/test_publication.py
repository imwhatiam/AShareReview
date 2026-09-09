from datetime import date, datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from kaipanla.services.fetcher import (
    KaipanlaSectorFundFlowFetchResult,
)
from kaipanla.services.parser import KaipanlaSectorFundFlowRow


class KaipanlaSnapshotPublicationTests(TestCase):
    databases = {'default', 'kaipanla'}

    def setUp(self):
        self.snapshot_time = timezone.make_aware(datetime(2026, 9, 8, 10, 5))
        self.row = KaipanlaSectorFundFlowRow(
            sector_code='BK001',
            sector_name='半导体',
            change_pct=Decimal('1.2'),
            main_net_inflow=Decimal('20'),
            main_buy=Decimal('30'),
            main_sell=Decimal('10'),
            large_order_net_inflow=Decimal('4'),
            volume_ratio=Decimal('1.1'),
            turnover_amount=Decimal('100'),
            float_market_cap=Decimal('50'),
            total_market_cap=Decimal('60'),
        )

    def test_complete_fetch_writes_the_snapshot_and_complete_run_to_kaipanla_database(self):
        from kaipanla.models import KaipanlaSectorFundFlowRun, KaipanlaSectorFundFlowSnapshot
        from kaipanla.services.writer import write_complete_snapshot

        outcome = write_complete_snapshot(
            fetch_result=KaipanlaSectorFundFlowFetchResult(
                rows=(self.row,),
                is_complete=True,
                expected_page_count=1,
                completed_page_count=1,
                failed_page_offsets=(),
                source_timestamp=1788833100,
                source_trade_date='2026-09-08',
            ),
            snapshot_time=self.snapshot_time,
            source_batch_id='batch-1',
        )

        self.assertEqual(outcome.record_count, 1)
        snapshot = KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').get()
        self.assertEqual(snapshot.trade_date, date(2026, 9, 8))
        self.assertEqual(snapshot.main_net_inflow, Decimal('20'))
        run = KaipanlaSectorFundFlowRun.objects.using('kaipanla').get()
        self.assertEqual(run.status, KaipanlaSectorFundFlowRun.Status.COMPLETE)
        self.assertEqual(run.actual_record_count, 1)

    def test_incomplete_fetch_cannot_write_or_publish_a_snapshot(self):
        from kaipanla.models import KaipanlaSectorFundFlowSnapshot
        from kaipanla.services.writer import IncompleteKaipanlaSnapshot, write_complete_snapshot

        with self.assertRaises(IncompleteKaipanlaSnapshot):
            write_complete_snapshot(
                fetch_result=KaipanlaSectorFundFlowFetchResult(
                    rows=(),
                    is_complete=False,
                    expected_page_count=2,
                    completed_page_count=1,
                    failed_page_offsets=(80,),
                    source_timestamp=1788833100,
                    source_trade_date='2026-09-08',
                    error_summary='A required page failed.',
                ),
                snapshot_time=self.snapshot_time,
                source_batch_id='batch-2',
            )

        self.assertFalse(KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').exists())
