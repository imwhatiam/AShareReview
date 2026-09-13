from datetime import date, timedelta
from decimal import Decimal

from django.test import SimpleTestCase

from core.services.contracts import MarketDataVersion, Industry
from hundred_day.services.analysis import (
    HistoricalCloseData,
    HundredDayStockDetail,
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
            data_version=MarketDataVersion('daily-prices-v1', self.business_date),
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
        self.assertEqual(
            summaries['I002'].new_high_stocks,
            (
                HundredDayStockDetail(
                    stock_code='600001',
                    stock_name='股票600001',
                    change_percent=Decimal('9.99'),
                    turnover=Decimal('1234567'),
                ),
            ),
        )
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
            industries=(Industry('I001', '电子', ('600001',)),),
        )

        result = build_hundred_day_analysis(source, source_industry_version='industries-v1')

        self.assertEqual(result.valid_stock_count, 2)
        self.assertEqual(result.new_high_count, 2)
        self.assertEqual(result.industry_summaries[0].new_high_count, 1)
        self.assertEqual(result.trend_points[-1].new_high_ratio, Decimal('1'))

    def test_multiple_industries_receive_the_same_stock_flag(self):
        source = self._source(
            positions=100,
            industries=(
                Industry('I002', '半导体', ('600001',)),
                Industry('I001', '电子', ('600001',)),
            ),
        )

        result = build_hundred_day_analysis(source, source_industry_version='industries-v1')

        self.assertEqual(
            [(summary.industry_code, summary.new_high_count) for summary in result.industry_summaries],
            [('I001', 1), ('I002', 1)],
        )
        self.assertEqual(
            result.stock_flags[0].industries,
            ({'code': 'I001', 'name': '电子'}, {'code': 'I002', 'name': '半导体'}),
        )

    def test_industry_details_carry_target_day_quotes_and_tolerate_missing_ones(self):
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
                # 600002 没有当日行情：明细仍要出现，但涨幅与成交额留空。
            },
        )

        result = build_hundred_day_analysis(source, source_industry_version='industries-v1')

        self.assertEqual(
            result.industry_summaries[0].new_high_stocks,
            (
                HundredDayStockDetail('600001', '股票600001', Decimal('10.5'), Decimal('9876543.21')),
                HundredDayStockDetail('600002', '股票600002', None, None),
            ),
        )

    def test_fails_explicitly_when_fewer_than_100_trade_day_positions_are_available(self):
        source = self._source(positions=99)

        with self.assertRaises(InsufficientHundredDayHistory):
            build_hundred_day_analysis(source, source_industry_version='industries-v1')
