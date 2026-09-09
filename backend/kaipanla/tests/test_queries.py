from datetime import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.models import TradingDay
from kaipanla.models import KaipanlaSectorFundFlowSnapshot


class KaipanlaQueryServiceTests(TestCase):
    databases = {'default', 'kaipanla'}

    def setUp(self):
        self.day_one = datetime(2026, 9, 7).date()
        self.day_two = datetime(2026, 9, 8).date()
        TradingDay.objects.bulk_create(
            [
                TradingDay(trade_date=self.day_one),
                TradingDay(trade_date=self.day_two),
            ]
        )

    def _snapshot(self, trade_date, hour, minute, code, name, net_inflow):
        snapshot_time = timezone.make_aware(datetime(
            trade_date.year, trade_date.month, trade_date.day, hour, minute
        ))
        return KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').create(
            sector_code=code,
            sector_name=name,
            trade_date=trade_date,
            snapshot_time=snapshot_time,
            main_net_inflow=Decimal(str(net_inflow)),
            source_batch_id=f'{trade_date}-{hour:02d}{minute:02d}',
        )

    def test_intraday_uses_fixed_five_minute_axis_and_stable_rankings(self):
        from kaipanla.services.intraday import query_intraday

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

    def test_history_reads_only_close_snapshots_and_reports_missing_dates(self):
        from kaipanla.services.history import query_intraday_history

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
        self.assertEqual([item['trade_date'] for item in payload['items']], ['2026-09-08', '2026-09-07'])
        self.assertEqual(payload['missing_trade_dates'], ['2026-09-08'])
        self.assertEqual(payload['items'][0]['time_points'], ['15:00'])
        self.assertEqual(payload['items'][0]['series'], [])
        self.assertEqual(payload['period_rankings']['inflows'][0]['code'], 'A')
        self.assertEqual(payload['period_rankings']['inflows'][0]['net_inflow_total'], 1.0)
        self.assertEqual(payload['period_rankings']['outflows'][0]['code'], 'B')
        self.assertEqual(payload['period_rankings']['outflows'][0]['net_inflow_total'], -2.0)

    def test_query_rejects_unsupported_window_and_ranking_limits(self):
        from kaipanla.services.history import query_intraday_history
        from kaipanla.services.intraday import query_intraday

        with self.assertRaisesRegex(ValueError, 'inflow_top'):
            query_intraday(self.day_two, inflow_top=31, outflow_top=0)
        with self.assertRaisesRegex(ValueError, 'days'):
            query_intraday_history(self.day_two, days=2, inflow_top=0, outflow_top=0)

    def test_history_uses_only_public_calendar_dates_and_empty_intraday_is_stable(self):
        from kaipanla.services.history import query_intraday_history
        from kaipanla.services.intraday import query_intraday

        self._snapshot(self.day_two, 15, 0, 'A', '甲行业', 100_000_000)

        history = query_intraday_history(
            datetime(2026, 9, 9).date(),
            days=1,
            inflow_top=1,
            outflow_top=1,
        )
        empty = query_intraday(
            self.day_one,
            now=timezone.make_aware(datetime(2026, 9, 8, 16, 0)),
        )

        self.assertEqual([item['trade_date'] for item in history['items']], ['2026-09-08'])
        self.assertEqual(empty, {
            'trade_date': '2026-09-07',
            'time_points': [],
            'series': [],
        })
