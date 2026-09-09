from datetime import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.models import TradingDay
from eastmoney.models import (
    EastmoneySectorFundFlowRun,
    EastmoneySectorFundFlowSnapshot,
)


class EastmoneyQueryServiceTests(TestCase):
    databases = {'default', 'eastmoney'}

    def setUp(self):
        self.day_one = datetime(2026, 9, 7).date()
        self.day_two = datetime(2026, 9, 8).date()
        TradingDay.objects.bulk_create(
            [
                TradingDay(trade_date=self.day_one),
                TradingDay(trade_date=self.day_two),
            ]
        )

    def _run(self, trade_date, hour, minute, *, status='complete'):
        source_batch_id = f'{trade_date}-{hour:02d}{minute:02d}-{status}'
        snapshot_time = timezone.make_aware(
            datetime(trade_date.year, trade_date.month, trade_date.day, hour, minute)
        )
        statuses = {
            'complete': (
                EastmoneySectorFundFlowRun.DirectionStatus.COMPLETE,
                EastmoneySectorFundFlowRun.DirectionStatus.COMPLETE,
            ),
            'partial_inflow': (
                EastmoneySectorFundFlowRun.DirectionStatus.COMPLETE,
                EastmoneySectorFundFlowRun.DirectionStatus.FAILED,
            ),
            'partial_outflow': (
                EastmoneySectorFundFlowRun.DirectionStatus.FAILED,
                EastmoneySectorFundFlowRun.DirectionStatus.COMPLETE,
            ),
        }
        inflow_status, outflow_status = statuses[status]
        EastmoneySectorFundFlowRun.objects.using('eastmoney').get_or_create(
            source_batch_id=source_batch_id,
            defaults={
                'trade_date': trade_date,
                'snapshot_time': snapshot_time,
                'status': 'partial' if status.startswith('partial_') else status,
                'inflow_status': inflow_status,
                'outflow_status': outflow_status,
            },
        )
        return source_batch_id, snapshot_time

    def _snapshot(self, trade_date, hour, minute, code, name, net_inflow, *, status='complete'):
        source_batch_id, snapshot_time = self._run(trade_date, hour, minute, status=status)
        return EastmoneySectorFundFlowSnapshot.objects.using('eastmoney').create(
            sector_code=code,
            sector_name=name,
            trade_date=trade_date,
            snapshot_time=snapshot_time,
            main_net_inflow=Decimal(str(net_inflow)) if net_inflow is not None else None,
            source_batch_id=source_batch_id,
        )

    def test_intraday_uses_fixed_five_minute_axis_and_stable_rankings(self):
        from eastmoney.services.intraday import query_intraday

        self._snapshot(self.day_two, 9, 30, 'A', '甲行业', 100_000_000)
        self._snapshot(self.day_two, 9, 30, 'B', '乙行业', -200_000_000)
        self._snapshot(self.day_two, 10, 0, 'A', '甲行业', 200_000_000)
        self._snapshot(self.day_two, 10, 0, 'B', '乙行业', -300_000_000)
        self._snapshot(self.day_two, 10, 0, 'C', '丙行业', 200_000_000)

        payload = query_intraday(
            self.day_two,
            inflow_top=1,
            outflow_top=1,
            now=timezone.make_aware(datetime(2026, 9, 8, 11, 0)),
        )

        self.assertEqual(payload['trade_date'], '2026-09-08')
        self.assertEqual(payload['time_points'][0], '09:30')
        self.assertEqual(payload['time_points'][-1], '11:00')
        self.assertEqual(len(payload['time_points']), 19)
        self.assertEqual([item['code'] for item in payload['series']], ['A', 'B'])
        self.assertEqual(payload['series'][0]['data'][0], 1.0)
        self.assertEqual(payload['series'][0]['data'][-1], 2.0)
        self.assertEqual(payload['series'][1]['data'][0], -2.0)
        self.assertEqual(payload['series'][1]['data'][-1], -3.0)
        self.assertEqual(payload['completeness'], 'complete')
        self.assertEqual(payload['missing_directions'], [])

    def test_intraday_keeps_partial_status_and_names_missing_direction(self):
        from eastmoney.services.intraday import query_intraday

        self._snapshot(
            self.day_two,
            10,
            0,
            'A',
            '甲行业',
            200_000_000,
            status='partial_inflow',
        )

        payload = query_intraday(
            self.day_two,
            inflow_top=1,
            outflow_top=1,
            now=timezone.make_aware(datetime(2026, 9, 8, 10, 0)),
        )

        self.assertEqual(payload['completeness'], 'partial')
        self.assertEqual(payload['missing_directions'], ['outflow'])
        self.assertEqual([item['code'] for item in payload['series']], ['A'])

    def test_history_reads_only_close_snapshots_and_reports_missing_dates(self):
        from eastmoney.services.history import query_intraday_history

        self._snapshot(self.day_one, 15, 0, 'A', '甲行业', 100_000_000)
        self._snapshot(self.day_one, 15, 0, 'B', '乙行业', -200_000_000)
        self._snapshot(self.day_two, 14, 55, 'A', '甲行业', 999_000_000)

        payload = query_intraday_history(
            self.day_two,
            days=5,
            inflow_top=1,
            outflow_top=1,
        )

        self.assertEqual(payload['end_date'], '2026-09-08')
        self.assertEqual(
            [item['trade_date'] for item in payload['items']],
            ['2026-09-08', '2026-09-07'],
        )
        self.assertEqual(payload['missing_trade_dates'], ['2026-09-08'])
        self.assertEqual(payload['items'][0]['time_points'], ['15:00'])
        self.assertEqual(payload['items'][0]['series'], [])
        self.assertEqual(payload['period_rankings']['inflows'][0]['code'], 'A')
        self.assertEqual(payload['period_rankings']['inflows'][0]['net_inflow_total'], 1.0)
        self.assertEqual(payload['period_rankings']['outflows'][0]['code'], 'B')
        self.assertEqual(payload['period_rankings']['outflows'][0]['net_inflow_total'], -2.0)

    def test_query_rejects_unsupported_window_and_ranking_limits(self):
        from eastmoney.services.history import query_intraday_history
        from eastmoney.services.intraday import query_intraday

        with self.assertRaisesRegex(ValueError, 'inflow_top'):
            query_intraday(self.day_two, inflow_top=31, outflow_top=0)
        with self.assertRaisesRegex(ValueError, 'days'):
            query_intraday_history(self.day_two, days=2, inflow_top=0, outflow_top=0)

    def test_query_allows_zero_ranking_limits_without_selecting_series(self):
        from eastmoney.services.intraday import query_intraday

        self._snapshot(self.day_two, 10, 0, 'A', '甲行业', 200_000_000)

        payload = query_intraday(
            self.day_two,
            inflow_top=0,
            outflow_top=0,
            now=timezone.make_aware(datetime(2026, 9, 8, 10, 0)),
        )

        self.assertEqual(payload['series'], [])
        self.assertEqual(payload['completeness'], 'complete')

    def test_history_propagates_partial_direction_warning(self):
        from eastmoney.services.history import query_intraday_history

        self._snapshot(
            self.day_one,
            15,
            0,
            'A',
            '甲行业',
            100_000_000,
            status='partial_inflow',
        )

        payload = query_intraday_history(
            self.day_one,
            days=1,
            inflow_top=1,
            outflow_top=0,
        )

        self.assertEqual(payload['completeness'], 'partial')
        self.assertEqual(payload['missing_directions'], ['outflow'])
