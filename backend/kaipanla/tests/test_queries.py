from datetime import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from kaipanla.models import KaipanlaSectorFundFlowSnapshot


class KaipanlaQueryServiceTests(TestCase):
    databases = {'kaipanla'}

    def setUp(self):
        self.day_one = datetime(2026, 9, 7).date()
        self.day_two = datetime(2026, 9, 8).date()

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
        )

    def _seed_two_slot_morning(self):
        """两个采集时点的上午：09:30 只有 A/B，10:00 追加 C。"""
        self._snapshot(self.day_two, 9, 30, 'A', '甲行业', 100_000_000)
        self._snapshot(self.day_two, 9, 30, 'B', '乙行业', -200_000_000)
        self._snapshot(self.day_two, 10, 0, 'A', '甲行业', 200_000_000)
        self._snapshot(self.day_two, 10, 0, 'B', '乙行业', -300_000_000)
        self._snapshot(self.day_two, 10, 0, 'C', '丙行业', 200_000_000)

    def _stamp_written_at(self, trade_date, hour, minute, when):
        """改写某一槽那批行的写入时刻，并返回改动的行数。

        ``created_at`` 是 ``auto_now_add``，只能在写完之后回填 —— 这正是"这一槽是
        什么时候写进库的"在测试里唯一可控的入口。
        """
        snapshot_time = timezone.make_aware(datetime(
            trade_date.year, trade_date.month, trade_date.day, hour, minute
        ))
        return KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').filter(
            trade_date=trade_date, snapshot_time=snapshot_time
        ).update(created_at=when)

    def test_intraday_axis_spans_the_whole_session_however_far_the_day_has_run(self):
        """横轴长度不随"现在几点"变化：只采集到 10:00 也要给出到 15:00 的整条刻度。"""
        from kaipanla.services.intraday import query_intraday

        self._seed_two_slot_morning()

        payload = query_intraday(self.day_two, inflow_top=1, outflow_top=1)

        self.assertEqual(payload['trade_date'], '2026-09-08')
        self.assertEqual(payload['time_points'][0], '09:30')
        self.assertEqual(payload['time_points'][-1], '15:00')
        # 上午 09:30–11:30 与下午 13:00–15:00 各 25 个五分钟槽，一段都不少；
        # 下午的刻度必须在场 —— 这才是"始终显示交易时段的时间刻度"。
        self.assertEqual(len(payload['time_points']), 50)
        self.assertEqual(payload['time_points'].count('11:30'), 1)
        self.assertEqual(payload['time_points'].count('13:00'), 1)
        self.assertNotIn('12:00', payload['time_points'])

        # 曲线只覆盖到最后一个已采集的时点（10:00），其后的交易时间留白。
        collected = payload['time_points'].index('10:00') + 1
        for item in payload['series']:
            self.assertEqual(len(item['data']), collected)

    def test_intraday_reads_the_stored_rows_without_asking_whether_they_are_published(self):
        """库里有什么就读什么。

        这条用例以前是"未发布的行不可见"：写行与发布分属两个库，行先落库、版本后
        标 complete，中间那批行必须被过滤掉。现在两者是同一件事（写行即发布），
        所以"最新槽位的行就是数据"本身成了契约。
        """
        from kaipanla.services.intraday import query_intraday

        self._snapshot(self.day_two, 15, 0, 'A', '甲行业', 100_000_000)

        payload = query_intraday(self.day_two, inflow_top=1, outflow_top=1)

        self.assertEqual([item['code'] for item in payload['series']], ['A'])
        self.assertEqual(payload['series'][0]['latest_net_inflow'], 1.0)

    def test_intraday_forward_fills_only_inside_collected_slots_and_ranks_by_latest(self):
        from kaipanla.services.intraday import query_intraday

        self._seed_two_slot_morning()

        payload = query_intraday(self.day_two, inflow_top=1, outflow_top=1)

        # 09:30 之后到 10:00 之间没有新快照：中间五个槽沿用 09:30 的值。
        self.assertEqual(payload['series'][0]['data'], [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 2.0])
        self.assertEqual(payload['series'][1]['data'][0], -2.0)
        self.assertEqual(payload['series'][1]['data'][-1], -3.0)
        # 榜单按最新快照（10:00）排序取值：C 只出现过一次，latest 就是它自己。
        self.assertEqual([item['code'] for item in payload['series']], ['A', 'B'])
        self.assertEqual(payload['series'][0]['latest_net_inflow'], 2.0)
        self.assertEqual(payload['series'][1]['latest_net_inflow'], -3.0)

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
        # 窗口整体来自交易日序列（core.services.calendar 推导）：09-08 起往前 5 个交易日，其中只有 09-07 有收盘快照。
        self.assertEqual(
            [item['trade_date'] for item in payload['items']],
            ['2026-09-08', '2026-09-07', '2026-09-04', '2026-09-03', '2026-09-02'],
        )
        self.assertEqual(
            payload['missing_trade_dates'],
            ['2026-09-08', '2026-09-04', '2026-09-03', '2026-09-02'],
        )
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

    def test_history_window_comes_from_trading_days_not_from_stored_snapshots(self):
        """窗口由交易日序列决定：某天没有快照也要出现在窗口里并标为缺失。"""
        from kaipanla.services.history import query_intraday_history
        from kaipanla.services.intraday import query_intraday

        self._snapshot(self.day_two, 15, 0, 'A', '甲行业', 100_000_000)

        history = query_intraday_history(
            datetime(2026, 9, 9).date(),
            days=1,
            inflow_top=1,
            outflow_top=1,
        )
        empty = query_intraday(self.day_one, inflow_top=1, outflow_top=1)

        # 09-09 是交易日但没有快照：窗口仍返回它，并如实标为缺失。
        self.assertEqual([item['trade_date'] for item in history['items']], ['2026-09-09'])
        self.assertEqual(history['missing_trade_dates'], ['2026-09-09'])
        self.assertEqual(history['items'][0]['series'], [])
        # 一条快照都没有的交易日连横轴都不给：空态由"没有曲线"决定，
        # 不是画一张只有刻度的空图。
        self.assertEqual(empty, {
            'trade_date': '2026-09-07',
            'time_points': [],
            'series': [],
        })

    def test_the_latest_helpers_answer_from_this_table_only(self):
        from kaipanla.services.queries import (
            latest_snapshot,
            latest_trade_date,
            list_trade_dates,
        )

        self.assertIsNone(latest_trade_date())
        self.assertEqual(latest_snapshot(self.day_two), (None, None))

        self._seed_two_slot_morning()
        self._snapshot(self.day_one, 15, 0, 'A', '甲行业', 100_000_000)

        self.assertEqual(latest_trade_date(), self.day_two)
        newest_slot, written_at = latest_snapshot(self.day_two)
        self.assertEqual(timezone.localtime(newest_slot).strftime('%H:%M'), '10:00')
        # 同一次查询顺带给出"最新槽那批行是什么时候写进库的"：页面上「更新于」
        # 显示的就是它，所以它必须来自最新槽，而不是这一天里最早或最晚写入的行。
        self.assertIsNotNone(written_at)
        self.assertEqual(list_trade_dates(), [self.day_two, self.day_one])

    def test_the_write_stamp_comes_from_the_newest_slot(self):
        """最新槽赢了，它那批行的写入时刻才跟着赢。

        快照一槽一批地写：09:30 那槽可能是很久以前写的，10:00 那槽是刚写的。页面上的
        资金流来自最新槽，时间戳也必须来自它 —— 取 min/max(created_at) 全表都不对。
        同一槽里多行取**最晚**的那次写入（一槽就是一个事务，正常应当一致）。
        """
        from kaipanla.services.queries import latest_snapshot

        self._seed_two_slot_morning()
        self._stamp_written_at(self.day_two, 9, 30, timezone.make_aware(
            datetime(2026, 9, 8, 9, 30, 5)
        ))
        self._stamp_written_at(self.day_two, 10, 0, timezone.make_aware(
            datetime(2026, 9, 8, 10, 0, 7)
        ))

        newest_slot, written_at = latest_snapshot(self.day_two)

        self.assertEqual(timezone.localtime(newest_slot).strftime('%H:%M'), '10:00')
        self.assertEqual(
            timezone.localtime(written_at).strftime('%H:%M:%S'), '10:00:07'
        )
