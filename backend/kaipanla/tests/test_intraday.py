from datetime import datetime

from django.test import TestCase
from django.utils import timezone

from kaipanla.services.intraday import resolve_snapshot_slot, session_slot


class SessionSlotTests(TestCase):
    """运行时刻在交易日当天落到哪个标准槽位上。"""

    def local(self, *parts):
        return timezone.make_aware(datetime(*parts))

    def test_moment_inside_a_session_floors_onto_its_own_five_minute_slot(self):
        self.assertEqual(
            session_slot(self.local(2026, 9, 11, 9, 33)),
            self.local(2026, 9, 11, 9, 30),
        )
        self.assertEqual(
            session_slot(self.local(2026, 9, 11, 10, 46)),
            self.local(2026, 9, 11, 10, 45),
        )
        self.assertEqual(
            session_slot(self.local(2026, 9, 11, 14, 22)),
            self.local(2026, 9, 11, 14, 20),
        )

    def test_midday_break_floors_onto_the_morning_close(self):
        self.assertEqual(
            session_slot(self.local(2026, 9, 11, 12, 0)),
            self.local(2026, 9, 11, 11, 30),
        )
        self.assertEqual(
            session_slot(self.local(2026, 9, 11, 12, 59)),
            self.local(2026, 9, 11, 11, 30),
        )

    def test_after_the_close_every_moment_lands_on_fifteen_hundred(self):
        self.assertEqual(
            session_slot(self.local(2026, 9, 11, 15, 0)),
            self.local(2026, 9, 11, 15, 0),
        )
        self.assertEqual(
            session_slot(self.local(2026, 9, 11, 16, 34)),
            self.local(2026, 9, 11, 15, 0),
        )
        self.assertEqual(
            session_slot(self.local(2026, 9, 11, 23, 10)),
            self.local(2026, 9, 11, 15, 0),
        )

    def test_before_the_open_the_day_has_no_reached_slot(self):
        self.assertIsNone(session_slot(self.local(2026, 9, 11, 9, 29)))
        self.assertIsNone(session_slot(self.local(2026, 9, 11, 3, 0)))


class ResolveSnapshotSlotTests(TestCase):
    """写入侧唯一的槽位判定：交易日回退到已到的槽，非交易日回退到上一交易日收盘。

    交易日由 `core.services.calendar` 按 `chinese-calendar` 判定；本地已没有日历
    表，所以"上一交易日"永远解析得出来，不再有"缺日历无法归属"的分支。
    """

    def local(self, *parts):
        return timezone.make_aware(datetime(*parts))

    def test_trading_day_run_floors_onto_the_slot_of_the_run_moment(self):
        for moment, expected in (
            ((2026, 9, 11, 9, 33), (2026, 9, 11, 9, 30)),
            ((2026, 9, 11, 10, 46), (2026, 9, 11, 10, 45)),
            ((2026, 9, 11, 14, 22), (2026, 9, 11, 14, 20)),
        ):
            with self.subTest(moment=moment):
                self.assertEqual(
                    resolve_snapshot_slot(self.local(*moment)),
                    self.local(*expected),
                )

    def test_midday_break_and_post_close_runs_land_on_the_morning_close_and_the_close(self):
        self.assertEqual(
            resolve_snapshot_slot(self.local(2026, 9, 11, 12, 30)),
            self.local(2026, 9, 11, 11, 30),
        )
        self.assertEqual(
            resolve_snapshot_slot(self.local(2026, 9, 11, 16, 34)),
            self.local(2026, 9, 11, 15, 0),
        )

    def test_non_trading_day_run_lands_on_the_previous_trading_close(self):
        # 2026-09-12 是周六、2026-09-13 是周日：无论几点运行都归到 09-11 的收盘。
        for moment in ((2026, 9, 12, 6, 41), (2026, 9, 12, 20, 0), (2026, 9, 13, 10, 0)):
            with self.subTest(moment=moment):
                self.assertEqual(
                    resolve_snapshot_slot(self.local(*moment)),
                    self.local(2026, 9, 11, 15, 0),
                )

    def test_statutory_holiday_run_lands_on_the_previous_trading_close(self):
        """2026-10-01 国庆（周四）休市，采集应归到 09-30 的收盘而不是当天槽位。"""
        self.assertEqual(
            resolve_snapshot_slot(self.local(2026, 10, 1, 10, 0)),
            self.local(2026, 9, 30, 15, 0),
        )

    def test_the_last_day_of_a_closure_lands_on_the_day_before_it(self):
        """国庆连休 10-01 至 10-07，10-07 运行仍归到 09-30 的收盘。"""
        self.assertEqual(
            resolve_snapshot_slot(self.local(2026, 10, 7, 10, 0)),
            self.local(2026, 9, 30, 15, 0),
        )

    def test_pre_open_run_on_a_trading_day_lands_on_the_previous_trading_close(self):
        self.assertEqual(
            resolve_snapshot_slot(self.local(2026, 9, 11, 9, 20)),
            self.local(2026, 9, 10, 15, 0),
        )

    def test_pre_open_run_after_a_closure_lands_on_the_last_close_before_it(self):
        """10-08 开盘前运行：上一交易日是 09-30，不是连休里的任何一天。"""
        self.assertEqual(
            resolve_snapshot_slot(self.local(2026, 10, 8, 9, 20)),
            self.local(2026, 9, 30, 15, 0),
        )
