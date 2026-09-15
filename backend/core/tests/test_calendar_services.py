"""交易日解析：`chinese-calendar` 是唯一来源，不再有本地日历表。

这些用例钉住"取交易日"的公开契约：周末与法定节假日一律不是交易日，任何"最近
一个交易日"的答案都必须落在真正的交易日上（上游历史接口只服务交易日，默认日期
落在周末或节假日会直接报错）。
"""

from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import chinese_calendar
from django.test import TestCase

from core.services import calendar as calendar_service
from core.services.calendar import (
    calendar_coverage,
    covered_year_range,
    is_trading_day,
    is_trading_session,
    latest_eligible_trading_day,
    latest_trading_date,
    previous_trading_day,
    recent_trading_days,
    to_shanghai_date,
    trading_days_between,
)

SHANGHAI = ZoneInfo('Asia/Shanghai')


def _at(*parts):
    return datetime(*parts, tzinfo=SHANGHAI)


class IsTradingDayTests(TestCase):
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
        self.assertFalse(is_trading_day(date(2026, 9, 25)))  # 中秋，周五

    def test_ordinary_weekdays_are_trading_days(self):
        self.assertTrue(is_trading_day(date(2026, 9, 11)))  # 周五
        self.assertTrue(is_trading_day(date(2026, 9, 14)))  # 周一
        self.assertTrue(is_trading_day(date(2026, 10, 8)))  # 国庆后第一个周四


class IsTradingSessionTests(TestCase):
    """默认模式闸门：既要落在交易日，也要落在 09:30-11:30 / 13:00-15:00 之内。

    采集命令用这个函数决定"要不要真的去上游取数"，所以四个边界整点（09:30、11:30、
    13:00、15:00）**所在的整一分钟**都算盘中，午休与盘后必须排除。
    """

    def test_both_session_boundaries_are_inclusive(self):
        for hour, minute in ((9, 30), (11, 30), (13, 0), (15, 0)):
            with self.subTest(moment=(hour, minute)):
                self.assertTrue(is_trading_session(_at(2026, 9, 14, hour, minute)))

    def test_the_whole_minute_of_a_boundary_clock_face_is_in_session(self):
        """边界整点的整一分钟都算盘中 —— 否则 11:30 这一槽永远采不到。

        调度是"到点拉起新进程"：cron 在 11:30:00.890 触发，进程读到时钟时已经是
        11:30:01.304。若只在 11:30:00.000000 这一微秒算盘中，`*/5 9-15` 的
        11:30 那一轮每天都被闸门拒掉，库里就永远缺 11:30 槽（15:00 同样越界，只是
        另有 `--latest` 兜底才没暴露）。
        """
        for hour, minute, second in (
            (9, 30, 1), (9, 30, 59),
            (11, 30, 1), (11, 30, 30), (11, 30, 59),
            (13, 0, 30),
            (15, 0, 1), (15, 0, 59),
        ):
            with self.subTest(moment=(hour, minute, second)):
                self.assertTrue(is_trading_session(_at(2026, 9, 14, hour, minute, second)))

    def test_the_midday_break_and_the_fringes_are_outside(self):
        """放宽只到整分钟为止：11:31 与 15:01 起仍是盘外，午休一整段都不被吞进来。"""
        for hour, minute, second in (
            (9, 29, 0), (9, 29, 59),
            (11, 31, 0), (11, 31, 30),
            (12, 0, 0), (12, 59, 59),
            (15, 1, 0),
            (23, 59, 59),
        ):
            with self.subTest(moment=(hour, minute, second)):
                self.assertFalse(is_trading_session(_at(2026, 9, 14, hour, minute, second)))

    def test_a_non_trading_day_is_outside_even_inside_the_clock_window(self):
        self.assertFalse(is_trading_session(_at(2026, 9, 12, 10, 0)))  # 周六
        self.assertFalse(is_trading_session(_at(2026, 10, 1, 10, 0)))  # 国庆，周四

    def test_a_naive_moment_is_read_as_shanghai_time(self):
        self.assertTrue(is_trading_session(datetime(2026, 9, 14, 10, 0)))
        self.assertFalse(is_trading_session(datetime(2026, 9, 14, 12, 0)))

    def test_defaults_to_the_current_moment(self):
        with patch('django.utils.timezone.now', return_value=_at(2026, 9, 14, 10, 0)):
            self.assertTrue(is_trading_session())
        with patch('django.utils.timezone.now', return_value=_at(2026, 9, 14, 12, 0)):
            self.assertFalse(is_trading_session())


class LatestTradingDateTests(TestCase):
    """上游历史接口只服务交易日，默认日期必须落在交易日上。"""

    def test_a_trading_query_day_resolves_to_itself(self):
        self.assertEqual(latest_trading_date(_at(2026, 9, 11, 10, 0)), date(2026, 9, 11))

    def test_weekend_query_resolves_back_to_the_previous_friday(self):
        self.assertEqual(latest_trading_date(_at(2026, 9, 12, 9, 30)), date(2026, 9, 11))
        self.assertEqual(latest_trading_date(_at(2026, 9, 13, 9, 30)), date(2026, 9, 11))

    def test_statutory_holiday_resolves_back_to_the_previous_weekday(self):
        """2026-10-01 国庆（周四），必须回退到 09-30 而不是当天。"""
        self.assertEqual(latest_trading_date(_at(2026, 10, 1, 10, 0)), date(2026, 9, 30))

    def test_a_long_closure_resolves_to_the_day_before_it(self):
        """国庆连休 10-01 至 10-07，10-07 的答案仍是 09-30。"""
        self.assertEqual(latest_trading_date(_at(2026, 10, 7, 10, 0)), date(2026, 9, 30))

    def test_naive_moment_is_treated_as_shanghai_time(self):
        self.assertEqual(
            latest_trading_date(datetime(2026, 9, 11, 10, 0)), date(2026, 9, 11)
        )


class PreviousTradingDayTests(TestCase):
    def test_steps_over_a_weekend(self):
        self.assertEqual(previous_trading_day(date(2026, 9, 14)), date(2026, 9, 11))

    def test_steps_over_a_holiday_closure(self):
        self.assertEqual(previous_trading_day(date(2026, 10, 1)), date(2026, 9, 30))
        self.assertEqual(previous_trading_day(date(2026, 10, 8)), date(2026, 9, 30))


class TradingDayWindowTests(TestCase):
    def test_recent_trading_days_are_newest_first_and_skip_non_trading_days(self):
        self.assertEqual(
            recent_trading_days(date(2026, 9, 8), count=5),
            [
                date(2026, 9, 8),
                date(2026, 9, 7),
                date(2026, 9, 4),
                date(2026, 9, 3),
                date(2026, 9, 2),
            ],
        )

    def test_recent_trading_days_never_exceed_the_requested_count(self):
        self.assertEqual(len(recent_trading_days(date(2026, 9, 8), count=3)), 3)

    def test_trading_days_between_is_inclusive_and_ascending(self):
        self.assertEqual(
            trading_days_between(date(2026, 9, 3), date(2026, 9, 8)),
            (date(2026, 9, 3), date(2026, 9, 4), date(2026, 9, 7), date(2026, 9, 8)),
        )

    def test_trading_days_between_spans_a_closure_without_inventing_days(self):
        self.assertEqual(
            trading_days_between(date(2026, 9, 30), date(2026, 10, 8)),
            (date(2026, 9, 30), date(2026, 10, 8)),
        )


class LatestEligibleTradingDayTests(TestCase):
    """盘后处理用的语义：当天收盘前仍算上一个交易日。"""

    def test_intraday_moment_still_resolves_to_the_previous_day(self):
        self.assertEqual(
            latest_eligible_trading_day(_at(2026, 9, 11, 10, 0)), date(2026, 9, 10)
        )

    def test_before_the_close_the_current_session_does_not_count(self):
        self.assertEqual(
            latest_eligible_trading_day(_at(2026, 9, 7, 14, 59, 59)), date(2026, 9, 4)
        )

    def test_at_the_close_the_current_trading_day_counts(self):
        self.assertEqual(
            latest_eligible_trading_day(_at(2026, 9, 7, 15, 0, 0)), date(2026, 9, 7)
        )

    def test_a_weekend_resolves_to_the_previous_trading_day(self):
        self.assertEqual(
            latest_eligible_trading_day(_at(2026, 9, 6, 11, 0)), date(2026, 9, 4)
        )

    def test_a_statutory_holiday_resolves_to_the_previous_trading_day(self):
        self.assertEqual(
            latest_eligible_trading_day(_at(2026, 10, 1, 11, 0)), date(2026, 9, 30)
        )


class UncoveredYearReportingTests(TestCase):
    """假期表未覆盖的年份必须留痕，否则"该升级依赖了"永远没人知道。

    退化方向是"工作日即交易日"，比真相更宽松：法定假日会被当成交易日提交给
    只服务交易日的上游。代价是不可见的，所以至少要有一条 WARNING。
    """

    def setUp(self):
        # 模块级集合跨用例存活，不清理就测不出"只报一次"。
        calendar_service._uncovered_years_reported.discard(2027)
        self.addCleanup(calendar_service._uncovered_years_reported.discard, 2027)

    def test_uncovered_year_warns_once_per_year_and_still_resolves_to_weekday(self):
        moment = _at(2027, 1, 4, 10, 0)

        with patch(
            'core.services.calendar.chinese_calendar.is_holiday',
            side_effect=NotImplementedError,
        ), self.assertLogs('core.services.calendar', level='WARNING') as captured:
            first = latest_trading_date(moment)
            second = latest_trading_date(moment)

        self.assertEqual(first, date(2027, 1, 4))
        self.assertEqual(second, date(2027, 1, 4))
        warnings = [
            record.getMessage()
            for record in captured.records
            if 'holiday_calendar_uncovered_year' in record.getMessage()
        ]
        self.assertEqual(len(warnings), 1, warnings)
        self.assertIn('year=2027', warnings[0])
        self.assertIn('weekday_treated_as_trading_day', warnings[0])

    def test_weekend_candidate_never_consults_the_holiday_table(self):
        """周末由 weekday() 直接判否，不必查假期表，也就不会误报"年份未覆盖"。"""
        moment = _at(2027, 1, 2, 10, 0)

        with patch(
            'core.services.calendar.chinese_calendar.is_holiday',
            side_effect=NotImplementedError,
        ) as is_holiday:
            resolved = latest_trading_date(moment)

        self.assertEqual(resolved, date(2027, 1, 1))
        consulted = [call.args[0] for call in is_holiday.call_args_list]
        self.assertTrue(consulted, '回溯到工作日时仍必须查表')
        self.assertTrue(all(day.weekday() < 5 for day in consulted), consulted)


class HolidayTableCoverageTests(TestCase):
    """依赖覆盖守卫：假期表按年内置，未覆盖的年份会静默退化。

    ``chinese-calendar`` 只带有限年份的假期表，超出范围的年份 ``is_holiday`` 抛
    ``NotImplementedError``，``is_trading_day`` 随即退化成"工作日即交易日"。退化方向
    偏宽松：法定假日会被当成交易日提交给只服务交易日的上游（开盘啦直接回 errcode
    1020），而唯一的安全兜底——上游日历——已经删除。

    所以这里钉住一条硬约束：**当前年份必须被覆盖**。测试在跨年当天变红是设计意图，
    它要求的动作是升级 ``requirements.txt`` 里的 ``chinese-calendar``，而不是改断言。
    健康检查里的 ``next_year_covered`` 是更早的预警信号。
    """

    def test_the_bundled_holiday_tables_cover_the_current_year(self):
        first_year, last_year = covered_year_range()
        current_year = to_shanghai_date().year

        self.assertTrue(
            first_year <= current_year <= last_year,
            f'chinese-calendar 只覆盖 {first_year}-{last_year}，当前年份是 {current_year}：'
            f'交易日判定会静默退化成"工作日即交易日"，且已无上游日历可兜底。'
            f'请升级 requirements.txt 里的 chinese-calendar。',
        )

    def test_the_reported_horizon_matches_what_is_holiday_actually_accepts(self):
        """守卫必须量真实边界，不能只量我们自己抄下来的常量。"""
        _, last_year = covered_year_range()

        chinese_calendar.is_holiday(date(last_year, 12, 31))  # 上界之内必须可查
        with self.assertRaises(NotImplementedError):
            chinese_calendar.is_holiday(date(last_year + 1, 1, 4))

    def test_coverage_report_is_derived_from_the_holiday_table(self):
        first_year, last_year = covered_year_range()
        report = calendar_coverage(_at(2026, 9, 14, 10, 0))

        self.assertEqual(report['covered_from'], first_year)
        self.assertEqual(report['covered_through'], last_year)
        self.assertEqual(
            report['covered_through_date'], date(last_year, 12, 31).isoformat()
        )
        self.assertEqual(report['current_year'], 2026)
        self.assertTrue(report['current_year_covered'])
        self.assertEqual(report['next_year_covered'], 2027 <= last_year)

    def test_coverage_report_flags_a_year_that_is_past_the_horizon(self):
        """覆盖报告必须能在越界年份自证"不覆盖"，否则它只是一个常量。"""
        _, last_year = covered_year_range()
        report = calendar_coverage(_at(last_year + 1, 1, 4, 10, 0))

        self.assertEqual(report['current_year'], last_year + 1)
        self.assertFalse(report['current_year_covered'])
        self.assertFalse(report['next_year_covered'])
