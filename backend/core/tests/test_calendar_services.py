"""交易日解析：上游历史接口只服务交易日，默认日期必须落在交易日上。"""

from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.utils import timezone

from core.models import TradingDay
from core.services import calendar as calendar_service
from core.services.calendar import latest_eligible_trading_day, latest_trading_date


class LatestTradingDateTests(TestCase):
    def _at(self, *parts):
        return timezone.make_aware(datetime(*parts))

    def test_synced_calendar_serves_the_query_day_when_it_is_a_trading_day(self):
        TradingDay.objects.bulk_create([
            TradingDay(trade_date=value) for value in (date(2026, 9, 10), date(2026, 9, 11))
        ])

        self.assertEqual(
            latest_trading_date(self._at(2026, 9, 11, 10, 0)),
            date(2026, 9, 11),
        )

    def test_weekend_query_resolves_back_to_the_previous_friday(self):
        TradingDay.objects.bulk_create([
            TradingDay(trade_date=value) for value in (date(2026, 9, 10), date(2026, 9, 11))
        ])

        # 2026-09-12 是周六，且日历里永远不会有这一行。
        self.assertEqual(
            latest_trading_date(self._at(2026, 9, 12, 9, 30)),
            date(2026, 9, 11),
        )

    def test_calendar_lagging_behind_does_not_pin_an_older_day(self):
        """日历只到 09-09 时不能用它当答案，否则会静默采集一周前的数据。"""
        TradingDay.objects.bulk_create([
            TradingDay(trade_date=value) for value in (date(2026, 9, 8), date(2026, 9, 9))
        ])

        self.assertEqual(
            latest_trading_date(self._at(2026, 9, 11, 10, 0)),
            date(2026, 9, 11),
        )

    def test_statutory_holiday_resolves_back_to_the_previous_weekday(self):
        """2026-10-01 国庆（周四），日历为空时靠法定节假日表回退。"""
        self.assertEqual(
            latest_trading_date(self._at(2026, 10, 1, 10, 0)),
            date(2026, 9, 30),
        )

    def test_year_without_holiday_data_falls_back_to_weekdays_only(self):
        """chinese-calendar 按年打包，未覆盖的年份只能保证跳过周末。"""
        self.assertEqual(
            latest_trading_date(self._at(2027, 1, 4, 10, 0)),
            date(2027, 1, 4),
        )

    def test_naive_moment_is_treated_as_shanghai_time(self):
        TradingDay.objects.create(trade_date=date(2026, 9, 11))

        self.assertEqual(
            latest_trading_date(datetime(2026, 9, 11, 10, 0)),
            date(2026, 9, 11),
        )

    def test_synced_calendar_still_wins_when_it_differs_from_the_holiday_table(self):
        """临时休市这类只在同花顺日历里的情况，以日历为准。"""
        TradingDay.objects.bulk_create([
            TradingDay(trade_date=value) for value in (date(2026, 9, 10), date(2026, 9, 15))
        ])

        # 09-11 到 09-14 日历里没有行，但日历已覆盖到未来，说明这几天确实休市。
        self.assertEqual(
            latest_trading_date(self._at(2026, 9, 14, 10, 0)),
            date(2026, 9, 10),
        )


class UncoveredYearReportingTests(TestCase):
    """假期表未覆盖的年份必须留痕，否则"该升级依赖了"永远没人知道。

    退化方向是"工作日即交易日"，比真相更宽松：法定假日会被当成交易日提交给
    只服务交易日的上游。代价是不可见的，所以至少要有一条 WARNING。
    """

    def setUp(self):
        # 模块级集合跨用例存活，而其他用例（如 2027 年那条）也会往里写，
        # 不清理就测不出"只报一次"。
        calendar_service._uncovered_years_reported.discard(2027)
        self.addCleanup(calendar_service._uncovered_years_reported.discard, 2027)

    def test_uncovered_year_warns_once_per_year_and_still_resolves_to_weekday(self):
        moment = timezone.make_aware(
            datetime(2027, 1, 4, 10, 0), ZoneInfo('Asia/Shanghai')
        )

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
        moment = timezone.make_aware(
            datetime(2027, 1, 2, 10, 0), ZoneInfo('Asia/Shanghai')
        )

        with patch(
            'core.services.calendar.chinese_calendar.is_holiday',
            side_effect=NotImplementedError,
        ) as is_holiday:
            resolved = latest_trading_date(moment)

        self.assertEqual(resolved, date(2027, 1, 1))
        consulted = [call.args[0] for call in is_holiday.call_args_list]
        self.assertTrue(consulted, '回溯到工作日时仍必须查表')
        self.assertTrue(all(day.weekday() < 5 for day in consulted), consulted)


class LatestEligibleTradingDayUnchangedTests(TestCase):
    """新函数不能改变盘后处理用的旧语义（当天收盘前仍算上一个交易日）。"""

    def test_intraday_moment_still_resolves_to_the_previous_day(self):
        TradingDay.objects.bulk_create([
            TradingDay(trade_date=value) for value in (date(2026, 9, 10), date(2026, 9, 11))
        ])
        # 时区写死：用例断言的是"收盘前仍算上一个交易日"这条语义，
        # 不该被本机 .env 的 TIME_ZONE 影响。
        moment = timezone.make_aware(
            datetime(2026, 9, 11, 10, 0), ZoneInfo('Asia/Shanghai')
        )

        with patch('django.utils.timezone.now', return_value=moment):
            self.assertEqual(latest_eligible_trading_day(), date(2026, 9, 10))
