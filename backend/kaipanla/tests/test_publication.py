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
                upstream_record_count=1,
            ),
            snapshot_time=self.snapshot_time,
            source_batch_id='batch-1',
            source_data_version='kaipanla-batch-version',
        )

        self.assertEqual(outcome.record_count, 1)
        snapshot = KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').get()
        self.assertEqual(snapshot.trade_date, date(2026, 9, 8))
        self.assertEqual(snapshot.main_net_inflow, Decimal('20'))
        # 行带着发布它的版本号：读路径只服务已发布版本的行。
        self.assertEqual(snapshot.source_data_version, 'kaipanla-batch-version')
        run = KaipanlaSectorFundFlowRun.objects.using('kaipanla').get()
        self.assertEqual(run.status, KaipanlaSectorFundFlowRun.Status.COMPLETE)
        self.assertEqual(run.actual_record_count, 1)
        self.assertEqual(run.missing_record_count, 0)

    def test_rows_the_upstream_counted_but_never_delivered_are_reported(self):
        """``missing_record_count`` 必须说真话。

        以前它恒为 0、且 expected 直接取"实际收到的行数"：完整性校验自证成立，
        运维最依赖的两个字段完全没有信息量。现在 expected 取上游 Count，差值
        就是"上游说有、我们没拿到"的行数。
        """
        from kaipanla.models import KaipanlaSectorFundFlowRun
        from kaipanla.services.writer import write_complete_snapshot

        write_complete_snapshot(
            fetch_result=KaipanlaSectorFundFlowFetchResult(
                rows=(self.row,),
                is_complete=True,
                expected_page_count=1,
                completed_page_count=1,
                failed_page_offsets=(),
                source_timestamp=1788833100,
                source_trade_date='2026-09-08',
                upstream_record_count=4,
                invalid_row_count=2,
            ),
            snapshot_time=self.snapshot_time,
            source_batch_id='batch-3',
            source_data_version='kaipanla-batch-version',
        )

        run = KaipanlaSectorFundFlowRun.objects.using('kaipanla').get()
        self.assertEqual(run.expected_record_count, 4)
        self.assertEqual(run.actual_record_count, 1)
        self.assertEqual(run.missing_record_count, 3)

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
                source_data_version='kaipanla-batch-version',
            )

        self.assertFalse(KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').exists())
