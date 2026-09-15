from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase

from core.services.contracts import (
    CompleteMarketSnapshot,
    MarketPrice,
    Industry,
)
from sector_momentum.services.analysis import build_sector_momentum_analysis


class SectorMomentumAnalysisTests(SimpleTestCase):
    business_date = date(2026, 9, 8)

    def _price(self, code, change, turnover, *, valid=True, exchange='sse'):
        return MarketPrice(
            stock_code=code,
            thscode=f'{code}.SH',
            stock_name=f'股票{code}',
            exchange=exchange,
            trade_date=self.business_date,
            pre_close=None,
            open_price=None,
            high_price=None,
            low_price=None,
            close_price=None,
            change_percent=Decimal(change) if change is not None else None,
            volume=None,
            turnover=Decimal(turnover) if turnover is not None else None,
            has_valid_trade=valid,
        )

    def _snapshot(self, prices, industries):
        return CompleteMarketSnapshot(
            business_date=self.business_date,
            prices=tuple(prices),
            industries=tuple(industries),
        )

    def test_above_five_percent_excludes_exactly_five_percent_and_uses_score_formula(self):
        snapshot = self._snapshot(
            [
                self._price('600001', '8', '100'),
                self._price('600002', '7', '300'),
                self._price('600003', '5', '600'),
                self._price('600004', '-1', '1000'),
            ],
            [Industry('I1', '行业甲', ('600001', '600002', '600003'))],
        )

        analysis = build_sector_momentum_analysis(snapshot)

        ranking = analysis.rankings_by_metric['above_5pct'][0]
        self.assertEqual(ranking.stock_count, 2)
        self.assertEqual([item.stock_code for item in ranking.stocks], ['600001', '600002'])
        self.assertEqual(analysis.total_market_turnover, Decimal('2000'))
        self.assertEqual(ranking.average_change_percent, Decimal('7.5'))
        self.assertEqual(ranking.industry_turnover, Decimal('400'))
        self.assertEqual(ranking.market_turnover_ratio, Decimal('0.2'))
        self.assertEqual(ranking.score, Decimal('3.0'))

    def test_top_five_percent_uses_max_one_floor_and_stable_stock_code_tie_breaker(self):
        snapshot = self._snapshot(
            [
                self._price('600003', '9', '100'),
                self._price('600001', '9', '100'),
                self._price('600002', '8', '100'),
            ],
            [Industry('I1', '行业甲', ('600001',)), Industry('I2', '行业乙', ('600003',))],
        )

        analysis = build_sector_momentum_analysis(snapshot)

        rankings = analysis.rankings_by_metric['top_5_percent']
        # 3 只有效股票 → 5% 向下取整为 0，由 max(1, …) 下限抬到 1：样本只含涨幅
        # 最高的一只（并列时按代码升序取 600001）。下限若失效，这里会是空榜。
        self.assertEqual(len(rankings), 1)
        self.assertEqual(rankings[0].industry_code, 'I1')
        self.assertEqual([item.stock_code for item in rankings[0].stocks], ['600001'])

    def test_unmapped_stocks_stay_in_market_denominator_and_multi_mapped_stock_counts_per_parent(self):
        snapshot = self._snapshot(
            [
                self._price('600001', '8', '100'),
                self._price('600002', '7', '300'),
            ],
            [
                Industry('I1', '行业甲', ('600001',)),
                Industry('I2', '行业乙', ('600001',)),
            ],
        )

        analysis = build_sector_momentum_analysis(snapshot)

        self.assertEqual(analysis.unmapped_stock_count, 1)
        self.assertEqual(analysis.total_market_turnover, Decimal('400'))
        self.assertEqual(
            {ranking.industry_code for ranking in analysis.rankings_by_metric['above_5pct']},
            {'I1', 'I2'},
        )
        self.assertTrue(all(ranking.stock_count == 1 for ranking in analysis.rankings_by_metric['above_5pct']))

    def test_empty_valid_market_returns_empty_rankings_without_division_error(self):
        snapshot = self._snapshot(
            [self._price('600001', None, None, valid=False)],
            [Industry('I1', '行业甲', ('600001',))],
        )

        analysis = build_sector_momentum_analysis(snapshot)

        self.assertEqual(analysis.total_market_turnover, Decimal('0'))
        self.assertEqual(analysis.rankings_by_metric['above_5pct'], ())
        self.assertEqual(analysis.rankings_by_metric['top_5_percent'], ())
        self.assertEqual(analysis.rankings_by_metric['above_5pct'], ())
        self.assertEqual(analysis.rankings_by_metric['top_5_percent'], ())
