from datetime import date
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from core.services.contracts import (
    CompleteMarketSnapshot,
    MarketDataVersion,
    MarketPrice,
    ParentIndustry,
)
from core.services.market_data import CompleteMarketDataUnavailable
from core.models import DataVersion
from stock_moves.models import StockMoveItem, StockMoveResult, StockMoveRun


class BuildStockMovesCommandTests(TestCase):
    databases = {'default', 'stock_moves'}
    business_date = date(2026, 9, 8)

    def _snapshot(self, version='daily-prices-20260908-v1'):
        return CompleteMarketSnapshot(
            data_version=MarketDataVersion(version=version, business_date=self.business_date),
            prices=(
                MarketPrice(
                    stock_code='600001',
                    thscode='600001.SH',
                    stock_name='上证上涨',
                    exchange='sse',
                    trade_date=self.business_date,
                    pre_close=None,
                    open_price=None,
                    high_price=None,
                    low_price=None,
                    close_price=None,
                    change_percent=Decimal('8'),
                    volume=None,
                    turnover=Decimal('800000000'),
                    has_valid_trade=True,
                ),
            ),
            parent_industries=(ParentIndustry('I001', '银行', ('600001',)),),
        )

    @patch('stock_moves.management.commands.build_stock_moves.get_complete_market_snapshot')
    def test_writes_only_derived_stock_moves_records_for_complete_market_snapshot(self, snapshot):
        snapshot.return_value = self._snapshot()
        output = StringIO()

        call_command('build_stock_moves', '--date', '2026-09-08', stdout=output)

        result = StockMoveResult.objects.using('stock_moves').get()
        item = StockMoveItem.objects.using('stock_moves').get()
        run = StockMoveRun.objects.using('stock_moves').get()
        self.assertEqual(result.source_daily_price_version, 'daily-prices-20260908-v1')
        self.assertEqual(item.group, StockMoveItem.Group.SSE_RISE)
        self.assertEqual(item.parent_industries, [{'code': 'I001', 'name': '银行'}])
        self.assertEqual(run.status, StockMoveRun.Status.SUCCESS)
        self.assertEqual(run.published_result_id, result.pk)
        self.assertFalse(DataVersion.objects.exists())
        self.assertIn('built 1 stock-move records', output.getvalue())

    @patch('stock_moves.management.commands.build_stock_moves.get_complete_market_snapshot')
    def test_dry_run_does_not_write_results_or_runs(self, snapshot):
        snapshot.return_value = self._snapshot()

        call_command('build_stock_moves', '--date', '2026-09-08', '--dry-run')

        self.assertFalse(StockMoveResult.objects.using('stock_moves').exists())
        self.assertFalse(StockMoveRun.objects.using('stock_moves').exists())

    @patch('stock_moves.management.commands.build_stock_moves.get_complete_market_snapshot')
    def test_incomplete_public_data_does_not_publish_result_and_records_failure(self, snapshot):
        snapshot.side_effect = CompleteMarketDataUnavailable('no complete version')

        with self.assertRaises(CommandError):
            call_command('build_stock_moves', '--date', '2026-09-08')

        self.assertFalse(StockMoveResult.objects.using('stock_moves').exists())
        run = StockMoveRun.objects.using('stock_moves').get()
        self.assertEqual(run.status, StockMoveRun.Status.FAILED)
        self.assertIn('no complete version', run.error_summary)

    @patch('stock_moves.management.commands.build_stock_moves.get_complete_market_snapshot')
    def test_new_public_data_version_creates_identifiable_rebuilt_result(self, snapshot):
        snapshot.side_effect = [
            self._snapshot('daily-prices-20260908-v1'),
            self._snapshot('daily-prices-20260908-v2'),
        ]

        call_command('build_stock_moves', '--date', '2026-09-08')
        call_command('build_stock_moves', '--date', '2026-09-08')

        self.assertEqual(
            set(StockMoveResult.objects.using('stock_moves').values_list(
                'source_daily_price_version', flat=True
            )),
            {'daily-prices-20260908-v1', 'daily-prices-20260908-v2'},
        )
