from datetime import date, timedelta
from decimal import Decimal

from django.test import SimpleTestCase

from core.services.contracts import Industry
from hundred_day.services.analysis import (
    HistoricalCloseData,
    InsufficientHundredDayHistory,
    TargetDayQuote,
    build_hundred_day_analysis,
)


class HundredDayAnalysisTests(SimpleTestCase):
    business_date = date(2026, 9, 8)

    def _source(self, *, positions=199, closes=None, industries=(), quotes=None):
        days = tuple(
            self.business_date - timedelta(days=positions - index - 1)
            for index in range(positions)
        )
        default = [Decimal('10')] * (positions - 1) + [Decimal('11')]
        closes = closes or {'600001': default}
        quotes = quotes if quotes is not None else {
            stock_code: TargetDayQuote(
                change_percent=Decimal('9.99'), turnover=Decimal('1234567')
            )
            for stock_code in closes
        }
        return HistoricalCloseData(
            business_date=self.business_date,
            trading_days=days,
            close_prices_by_stock={
                stock_code: {day: close for day, close in zip(days, values)}
                for stock_code, values in closes.items()
            },
            stock_names_by_code={
                stock_code: f'股票{stock_code}' for stock_code in closes
            },
            industries=tuple(industries),
            target_day_quotes=quotes,
        )

    def test_builds_target_flags_parent_industry_summaries_and_100_point_trend(self):
        source = self._source(
            closes={
                '600001': [Decimal('10')] * 99 + [Decimal('12')] * 99 + [Decimal('13')],
                '600002': [Decimal('10')] * 99 + [Decimal('12')] * 99 + [Decimal('0')],
                '600003': [Decimal('10')] * 198 + [None],
            },
            industries=(
                Industry('I001', '电子', ('600001', '600002')),
                Industry('I002', '半导体', ('600001',)),
            ),
        )

        result = build_hundred_day_analysis(source)

        self.assertEqual(result.business_date, self.business_date)
        self.assertEqual(
            [(flag.stock_code, flag.is_new_high, flag.is_new_low) for flag in result.stock_flags],
            [('600001', True, False), ('600002', False, True)],
        )
        # 当日数字不挂在结果对象上：它就是趋势的最后一个点，也就是市场宽度表里业务日期
        # 那一行。新高低计数与两个占比都由读路径从个股标志/宽度行现算（tests/test_api.py）。
        last = result.trend_points[-1]
        self.assertEqual(last.trade_date, self.business_date)
        self.assertEqual(last.valid_stock_count, 2)
        self.assertEqual(last.new_high_count, 1)
        self.assertEqual(last.new_low_count, 1)
        summaries = {summary.industry_code: summary for summary in result.industry_summaries}
        self.assertEqual(summaries['I001'].stock_count, 2)
        self.assertEqual(summaries['I002'].stock_count, 1)
        # 行业明细名单不再落库：行业分析只留成分股数，行情挂在个股标志上。
        self.assertFalse(hasattr(summaries['I002'], 'new_high_stocks'))
        self.assertEqual(
            [(flag.stock_code, flag.change_percent, flag.turnover) for flag in result.stock_flags],
            [
                ('600001', Decimal('9.99'), Decimal('1234567')),
                ('600002', Decimal('9.99'), Decimal('1234567')),
            ],
        )
        self.assertEqual(len(result.trend_points), 100)

    def test_unmapped_stocks_remain_in_market_denominator_but_not_industry_summary(self):
        source = self._source(
            positions=100,
            closes={
                '600001': [None] * 99 + [Decimal('1')],
                '600002': [None] * 99 + [Decimal('1')],
            },
            industries=(Industry('I001', '电子', ('600001',)),),
        )

        result = build_hundred_day_analysis(source)

        # 全市场分母含未映射的 600002，行业汇总的分母不含它。
        last = result.trend_points[-1]
        self.assertEqual(last.valid_stock_count, 2)
        self.assertEqual(last.new_high_count, 2)
        self.assertEqual(
            [(summary.industry_code, summary.stock_count) for summary in result.industry_summaries],
            [('I001', 1)],
        )

    def test_multiple_industries_receive_the_same_stock_flag(self):
        source = self._source(
            positions=100,
            industries=(
                Industry('I002', '半导体', ('600001',)),
                Industry('I001', '电子', ('600001',)),
            ),
        )

        result = build_hundred_day_analysis(source)

        self.assertEqual(
            [(summary.industry_code, summary.stock_count) for summary in result.industry_summaries],
            [('I001', 1), ('I002', 1)],
        )
        self.assertEqual(
            result.stock_flags[0].industries,
            ({'code': 'I001', 'name': '电子'}, {'code': 'I002', 'name': '半导体'}),
        )

    def test_flags_carry_target_day_quotes_and_tolerate_missing_ones(self):
        source = self._source(
            positions=100,
            closes={
                '600001': [Decimal('10')] * 99 + [Decimal('11')],
                '600002': [Decimal('10')] * 99 + [Decimal('11')],
            },
            industries=(Industry('I001', '电子', ('600001', '600002')),),
            quotes={
                '600001': TargetDayQuote(
                    change_percent=Decimal('10.5'), turnover=Decimal('9876543.21')
                ),
                # 600002 没有当日行情：标志仍要出现，但涨幅与成交额留空。
            },
        )

        result = build_hundred_day_analysis(source)

        self.assertEqual(
            [(flag.stock_code, flag.change_percent, flag.turnover) for flag in result.stock_flags],
            [
                ('600001', Decimal('10.5'), Decimal('9876543.21')),
                ('600002', None, None),
            ],
        )

    def test_fails_explicitly_when_fewer_than_100_trade_day_positions_are_available(self):
        source = self._source(positions=99)

        with self.assertRaises(InsufficientHundredDayHistory):
            build_hundred_day_analysis(source)
