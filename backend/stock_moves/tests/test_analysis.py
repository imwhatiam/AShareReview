from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase

from core.services.contracts import (
    CompleteMarketSnapshot,
    MarketDataVersion,
    MarketPrice,
    ParentIndustry,
)
from stock_moves.models import StockMoveItem
from stock_moves.services.analysis import build_stock_move_analysis


class StockMoveAnalysisTests(SimpleTestCase):
    business_date = date(2026, 9, 8)

    def _price(
        self,
        code,
        exchange,
        change_percent,
        turnover,
        *,
        name=None,
        valid=True,
    ):
        return MarketPrice(
            stock_code=code,
            thscode=f'{code}.TEST',
            stock_name=name if name is not None else f'股票{code}',
            exchange=exchange,
            trade_date=self.business_date,
            pre_close=None,
            open_price=None,
            high_price=None,
            low_price=None,
            close_price=None,
            change_percent=Decimal(change_percent) if change_percent is not None else None,
            volume=None,
            turnover=Decimal(turnover) if turnover is not None else None,
            has_valid_trade=valid,
        )

    def _snapshot(self, prices, industries=()):
        return CompleteMarketSnapshot(
            data_version=MarketDataVersion(
                version='daily-prices-20260908-v1', business_date=self.business_date
            ),
            prices=tuple(prices),
            parent_industries=tuple(industries),
        )

    def test_uses_inclusive_thresholds_and_builds_all_four_exchange_groups(self):
        result = build_stock_move_analysis(self._snapshot([
            self._price('600001', 'sse', '8.000000', '800000000'),
            self._price('600002', 'sse', '-8.000000', '800000000'),
            self._price('000001', 'szse', '9.000000', '900000000'),
            self._price('000002', 'szse', '-9.000000', '900000000'),
            self._price('600003', 'sse', '7.999999', '900000000'),
            self._price('000003', 'szse', '-8.000000', '799999999.9999'),
        ]))

        self.assertEqual(
            [(item.group, item.stock_code) for item in result.items],
            [
                (StockMoveItem.Group.SSE_RISE, '600001'),
                (StockMoveItem.Group.SSE_FALL, '600002'),
                (StockMoveItem.Group.SZSE_RISE, '000001'),
                (StockMoveItem.Group.SZSE_FALL, '000002'),
            ],
        )
        self.assertEqual(result.group_counts, {
            StockMoveItem.Group.SSE_RISE: 1,
            StockMoveItem.Group.SSE_FALL: 1,
            StockMoveItem.Group.SZSE_RISE: 1,
            StockMoveItem.Group.SZSE_FALL: 1,
        })
        self.assertEqual(result.distinct_stock_count, 4)

    def test_sorts_rises_descending_falls_ascending_with_stock_code_tiebreaker(self):
        result = build_stock_move_analysis(self._snapshot([
            self._price('600003', 'sse', '9', '800000000'),
            self._price('600001', 'sse', '10', '800000000'),
            self._price('600002', 'sse', '9', '800000000'),
            self._price('000003', 'szse', '-9', '800000000'),
            self._price('000002', 'szse', '-10', '800000000'),
            self._price('000001', 'szse', '-9', '800000000'),
        ]))

        self.assertEqual(
            [(item.group, item.rank, item.stock_code) for item in result.items],
            [
                (StockMoveItem.Group.SSE_RISE, 1, '600001'),
                (StockMoveItem.Group.SSE_RISE, 2, '600002'),
                (StockMoveItem.Group.SSE_RISE, 3, '600003'),
                (StockMoveItem.Group.SZSE_FALL, 1, '000002'),
                (StockMoveItem.Group.SZSE_FALL, 2, '000001'),
                (StockMoveItem.Group.SZSE_FALL, 3, '000003'),
            ],
        )

    def test_excludes_bse_and_invalid_prices_but_returns_explicit_warnings(self):
        result = build_stock_move_analysis(self._snapshot([
            self._price('430001', 'bse', '10', '900000000'),
            self._price('600001', 'sse', '10', '900000000', name=''),
            self._price('000001', 'szse', None, '900000000'),
            self._price('000002', 'szse', '10', None),
            self._price('000003', 'szse', '10', '900000000', valid=False),
        ]))

        self.assertEqual([(item.group, item.stock_name) for item in result.items], [
            (StockMoveItem.Group.SSE_RISE, ''),
        ])
        self.assertTrue(any('北京证券交易所' in warning for warning in result.warnings))
        self.assertTrue(any('名称缺失' in warning for warning in result.warnings))

    def test_keeps_all_matching_parent_industry_labels_and_reports_unmapped_stocks(self):
        result = build_stock_move_analysis(self._snapshot(
            [
                self._price('600001', 'sse', '10', '900000000'),
                self._price('600002', 'sse', '10', '900000000'),
            ],
            [
                ParentIndustry('I002', '半导体', ('600001',)),
                ParentIndustry('I001', '电子', ('600001',)),
            ],
        ))

        item = result.items[0]
        self.assertEqual(item.parent_industries, (
            {'code': 'I001', 'name': '电子'},
            {'code': 'I002', 'name': '半导体'},
        ))
        self.assertTrue(any('600002' in warning and '未映射' in warning for warning in result.warnings))

    def test_allows_empty_groups(self):
        result = build_stock_move_analysis(self._snapshot([
            self._price('600001', 'sse', '1', '1'),
        ]))

        self.assertEqual(result.items, ())
        self.assertEqual(result.distinct_stock_count, 0)
        self.assertEqual(sum(result.group_counts.values()), 0)
