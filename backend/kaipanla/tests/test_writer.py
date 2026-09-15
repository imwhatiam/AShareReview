from datetime import date, datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from kaipanla.services.fetcher import KaipanlaSectorFundFlowFetchResult
from kaipanla.services.parser import KaipanlaSectorFundFlowRow


def make_row(code='BK001', name='半导体', net_inflow='20'):
    return KaipanlaSectorFundFlowRow(
        sector_code=code,
        sector_name=name,
        change_pct=Decimal('1.2'),
        main_net_inflow=Decimal(net_inflow),
        main_buy=Decimal('30'),
        main_sell=Decimal('10'),
        large_order_net_inflow=Decimal('4'),
        volume_ratio=Decimal('1.1'),
        turnover_amount=Decimal('100'),
        float_market_cap=Decimal('50'),
        total_market_cap=Decimal('60'),
    )


class KaipanlaSnapshotWriteTests(TestCase):
    """写行即发布：没有任何"标 complete 才算数"的第二步。"""

    databases = {'kaipanla'}

    def setUp(self):
        self.snapshot_time = timezone.make_aware(datetime(2026, 9, 8, 10, 5))

    def write(self, fetch_result, snapshot_time=None):
        from kaipanla.services.writer import write_complete_snapshot

        return write_complete_snapshot(
            fetch_result=fetch_result,
            snapshot_time=snapshot_time or self.snapshot_time,
        )

    def complete(self, *rows):
        return KaipanlaSectorFundFlowFetchResult(
            rows=rows,
            is_complete=True,
            expected_page_count=1,
            completed_page_count=1,
            failed_page_offsets=(),
            source_timestamp=1788833100,
            source_trade_date='2026-09-08',
            upstream_record_count=len(rows),
        )

    def test_a_complete_fetch_is_stored_and_readable_without_a_publish_step(self):
        from kaipanla.models import KaipanlaSectorFundFlowSnapshot

        written = self.write(self.complete(make_row()))

        self.assertEqual(written, 1)
        snapshot = KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').get()
        self.assertEqual(snapshot.trade_date, date(2026, 9, 8))
        self.assertEqual(snapshot.snapshot_time, self.snapshot_time)
        self.assertEqual(snapshot.main_net_inflow, Decimal('20'))

    def test_rewriting_the_same_slot_updates_the_rows_instead_of_duplicating_them(self):
        from kaipanla.models import KaipanlaSectorFundFlowSnapshot

        self.write(self.complete(make_row(), make_row('BK002', '医药')))
        self.write(
            self.complete(
                make_row(net_inflow='999'),
                make_row('BK002', '医药'),
                make_row('BK003', '券商'),
            )
        )

        stored = KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla')
        self.assertEqual(stored.count(), 3)
        self.assertEqual(
            sorted(stored.values_list('sector_code', flat=True)), ['BK001', 'BK002', 'BK003']
        )
        self.assertEqual(stored.get(sector_code='BK001').main_net_inflow, Decimal('999'))

    def test_an_incomplete_fetch_writes_nothing_at_all(self):
        from kaipanla.models import KaipanlaSectorFundFlowSnapshot
        from kaipanla.services.writer import IncompleteKaipanlaSnapshot

        with self.assertRaises(IncompleteKaipanlaSnapshot):
            self.write(
                KaipanlaSectorFundFlowFetchResult(
                    rows=(),
                    is_complete=False,
                    expected_page_count=2,
                    completed_page_count=1,
                    failed_page_offsets=(80,),
                    source_timestamp=1788833100,
                    source_trade_date='2026-09-08',
                    error_summary='A required page failed.',
                )
            )

        self.assertFalse(KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').exists())

    def test_a_fetch_that_parsed_no_rows_leaves_the_stored_snapshot_alone(self):
        """空快照不能把当天已有的行清掉 —— 不完整就是"什么都不做"。"""
        from kaipanla.models import KaipanlaSectorFundFlowSnapshot
        from kaipanla.services.writer import IncompleteKaipanlaSnapshot

        self.write(self.complete(make_row()))

        with self.assertRaises(IncompleteKaipanlaSnapshot):
            self.write(self.complete())

        stored = KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla')
        self.assertEqual(stored.count(), 1)
        self.assertEqual(stored.get().sector_code, 'BK001')
