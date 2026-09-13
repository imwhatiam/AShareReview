from datetime import date, datetime

from django.test import TestCase
from django.utils import timezone

from core.models import TradingDay
from kaipanla.services.intraday import is_trading_day, resolve_snapshot_slot, session_slot


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


class TradingDayFlagTests(TestCase):
    """交易日判定：周末与法定节假日都不算交易日（chinese-calendar + 同花顺日历）。"""

    databases = {'default'}

    def test_weekends_are_not_trading_days(self):
        self.assertFalse(is_trading_day(date(2026, 9, 12)))  # 周六
        self.assertFalse(is_trading_day(date(2026, 9, 13)))  # 周日

    def test_in_lieu_working_weekends_are_still_not_trading_days(self):
        """调休上班的周末：国家日历算工作日，但交易所休市。"""
        self.assertFalse(is_trading_day(date(2026, 9, 20)))  # 周日调休上班
        self.assertFalse(is_trading_day(date(2026, 5, 9)))  # 周六调休上班
        self.assertFalse(is_trading_day(date(2026, 1, 4)))  # 周日调休上班

    def test_statutory_holidays_on_weekdays_are_not_trading_days(self):
        self.assertFalse(is_trading_day(date(2026, 10, 1)))  # 国庆，周四
        self.assertFalse(is_trading_day(date(2026, 1, 1)))  # 元旦，周四
        self.assertFalse(is_trading_day(date(2026, 2, 17)))  # 春节，周二

    def test_ordinary_weekdays_are_trading_days_even_without_a_synced_calendar(self):
        """不能因为同花顺日历还没同步到今天就把交易日误判成节假日。"""
        self.assertFalse(TradingDay.objects.exists())

        self.assertTrue(is_trading_day(date(2026, 9, 11)))  # 周五
        self.assertTrue(is_trading_day(date(2026, 9, 14)))  # 周一

    def test_chinese_calendar_decides_a_weekday_even_when_the_synced_calendar_lacks_it(self):
        """有节假日数据的年份以 chinese-calendar 为准，这样日历没同步到当天也不会误判。"""
        TradingDay.objects.create(trade_date=date(2026, 9, 15))

        self.assertTrue(is_trading_day(date(2026, 9, 14)))
        self.assertTrue(is_trading_day(date(2026, 9, 15)))

    def test_year_without_holiday_data_falls_back_to_the_synced_calendar(self):
        """chinese-calendar 只内置到 2026 年；之后退回同花顺日历，不再自己猜节假日。"""
        TradingDay.objects.create(trade_date=date(2027, 1, 5))

        self.assertTrue(is_trading_day(date(2027, 1, 5)))  # 日历里有这一行
        self.assertFalse(is_trading_day(date(2027, 1, 4)))  # 日历已覆盖该日却没有它
        self.assertTrue(is_trading_day(date(2027, 1, 6)))  # 日历还没到该日，按工作日处理


class ResolveSnapshotSlotTests(TestCase):
    """写入侧唯一的槽位判定：交易日回退到已到的槽，非交易日回退到上一交易日收盘。"""

    def setUp(self):
        TradingDay.objects.bulk_create([
            TradingDay(trade_date=date(2026, 9, 10)),
            TradingDay(trade_date=date(2026, 9, 11)),
        ])

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
        """2026-10-01 国庆（周四）休市，采集应归到 09-11 的收盘而不是当天槽位。"""
        self.assertEqual(
            resolve_snapshot_slot(self.local(2026, 10, 1, 10, 0)),
            self.local(2026, 9, 11, 15, 0),
        )

    def test_pre_open_run_on_a_trading_day_lands_on_the_previous_trading_close(self):
        self.assertEqual(
            resolve_snapshot_slot(self.local(2026, 9, 11, 9, 20)),
            self.local(2026, 9, 10, 15, 0),
        )

    def test_weekday_beyond_the_calendar_window_counts_as_a_trading_day(self):
        # 日历最晚只到 09-11：09-14 当作交易日，否则当天数据会覆盖 09-11 的收盘快照。
        self.assertEqual(
            resolve_snapshot_slot(self.local(2026, 9, 14, 10, 3)),
            self.local(2026, 9, 14, 10, 0),
        )

    def test_missing_calendar_cannot_assign_a_snapshot(self):
        TradingDay.objects.all().delete()

        with self.assertRaises(ValueError):
            resolve_snapshot_slot(self.local(2026, 9, 12, 6, 41))
