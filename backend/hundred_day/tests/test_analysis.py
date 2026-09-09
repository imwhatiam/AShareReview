from datetime import date, timedelta
from decimal import Decimal

from django.test import SimpleTestCase

from core.services.contracts import MarketDataVersion, ParentIndustry
from hundred_day.services.analysis import (
    HistoricalCloseData,
    InsufficientHundredDayHistory,
    build_hundred_day_analysis,
)


class HundredDayAnalysisTests(SimpleTestCase):
    business_date = date(2026, 9, 8)

    def _source(self, *, positions=199, closes=None, industries=()):
        days = tuple(
            self.business_date - timedelta(days=positions - index - 1)
            for index in range(positions)
        )
        default = [Decimal('10')] * (positions - 1) + [Decimal('11')]
        closes = closes or {'600001': default}
        return HistoricalCloseData(
            data_version=MarketDataVersion('daily-prices-v1', self.business_date),
            trading_days=days,
            close_prices_by_stock={
                stock_code: {day: close for day, close in zip(days, values)}
                for stock_code, values in closes.items()
            },
            stock_names_by_code={
                stock_code: f'股票{stock_code}' for stock_code in closes
            },
            parent_industries=tuple(industries),
        )

    def test_builds_target_flags_parent_industry_summaries_and_100_point_trend(self):
        source = self._source(
            closes={
                '600001': [Decimal('10')] * 99 + [Decimal('12')] * 99 + [Decimal('13')],
                '600002': [Decimal('10')] * 99 + [Decimal('12')] * 99 + [Decimal('0')],
                '600003': [Decimal('10')] * 198 + [None],
            },
            industries=(
                ParentIndustry('I001', '电子', ('600001', '600002')),
                ParentIndustry('I002', '半导体', ('600001',)),
            ),
        )

        result = build_hundred_day_analysis(source, source_industry_version='industries-v1')

        self.assertEqual(result.business_date, self.business_date)
        self.assertEqual(result.valid_stock_count, 2)
        self.assertEqual(result.new_high_count, 1)
        self.assertEqual(result.new_low_count, 1)
        self.assertEqual(
            [(flag.stock_code, flag.is_new_high, flag.is_new_low) for flag in result.stock_flags],
            [('600001', True, False), ('600002', False, True)],
        )
        summaries = {summary.industry_code: summary for summary in result.industry_summaries}
        self.assertEqual(summaries['I001'].stock_count, 2)
        self.assertEqual(summaries['I001'].new_high_count, 1)
        self.assertEqual(summaries['I001'].new_low_count, 1)
        self.assertEqual(summaries['I002'].new_high_stocks, ({'code': '600001', 'name': '股票600001'},))
        self.assertEqual(len(result.trend_points), 100)
        self.assertEqual(result.trend_points[-1].trade_date, self.business_date)
        self.assertEqual(result.trend_points[-1].new_high_ratio, Decimal('0.5'))
        self.assertEqual(result.trend_points[-1].new_low_ratio, Decimal('0.5'))

    def test_unmapped_stocks_remain_in_market_denominator_but_not_industry_summary(self):
        source = self._source(
            positions=100,
            closes={
                '600001': [None] * 99 + [Decimal('1')],
                '600002': [None] * 99 + [Decimal('1')],
            },
            industries=(ParentIndustry('I001', '电子', ('600001',)),),
        )

        result = build_hundred_day_analysis(source, source_industry_version='industries-v1')

        self.assertEqual(result.valid_stock_count, 2)
        self.assertEqual(result.new_high_count, 2)
        self.assertEqual(result.industry_summaries[0].new_high_count, 1)
        self.assertEqual(result.trend_points[-1].new_high_ratio, Decimal('1'))

    def test_multiple_parent_industries_receive_the_same_stock_flag(self):
        source = self._source(
            positions=100,
            industries=(
                ParentIndustry('I002', '半导体', ('600001',)),
                ParentIndustry('I001', '电子', ('600001',)),
            ),
        )

        result = build_hundred_day_analysis(source, source_industry_version='industries-v1')

        self.assertEqual(
            [(summary.industry_code, summary.new_high_count) for summary in result.industry_summaries],
            [('I001', 1), ('I002', 1)],
        )
        self.assertEqual(
            result.stock_flags[0].parent_industries,
            ({'code': 'I001', 'name': '电子'}, {'code': 'I002', 'name': '半导体'}),
        )

    def test_fails_explicitly_when_fewer_than_100_trade_day_positions_are_available(self):
        source = self._source(positions=99)

        with self.assertRaises(InsufficientHundredDayHistory):
            build_hundred_day_analysis(source, source_industry_version='industries-v1')
