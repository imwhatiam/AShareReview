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
    Industry,
)
from core.services.market_data import CompleteMarketDataUnavailable
from core.models import DataVersion
from stock_moves.models import StockMoveItem, StockMoveResult, StockMoveRun
from stock_moves.services.source_versions import CompleteIndustrySnapshotUnavailable

INDUSTRY_VERSION = 'industries-20260908-v1'
_MARKET_SNAPSHOT = 'stock_moves.management.commands.build_stock_moves.get_complete_market_snapshot'
_INDUSTRY_VERSION = (
    'stock_moves.management.commands.build_stock_moves.get_complete_industry_snapshot_version'
)


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
            industries=(Industry('I001', '银行', ('600001',)),),
        )

    @patch(_INDUSTRY_VERSION)
    @patch(_MARKET_SNAPSHOT)
    def test_writes_only_derived_stock_moves_records_for_complete_market_snapshot(
        self, snapshot, industry_version
    ):
        snapshot.return_value = self._snapshot()
        industry_version.return_value = INDUSTRY_VERSION
        output = StringIO()

        call_command('build_stock_moves', '--date', '2026-09-08', stdout=output)

        result = StockMoveResult.objects.using('stock_moves').get()
        item = StockMoveItem.objects.using('stock_moves').get()
        run = StockMoveRun.objects.using('stock_moves').get()
        self.assertEqual(result.source_daily_price_version, 'daily-prices-20260908-v1')
        # 行业映射是第二个输入，命令必须把它一起写下来，读路径才能判断结果是否过期。
        self.assertEqual(result.source_industry_version, INDUSTRY_VERSION)
        self.assertEqual(run.source_industry_version, INDUSTRY_VERSION)
        self.assertEqual(item.group, StockMoveItem.Group.SSE_RISE)
        self.assertEqual(item.industries, [{'code': 'I001', 'name': '银行'}])
        self.assertEqual(run.status, StockMoveRun.Status.SUCCESS)
        self.assertEqual(run.published_result_id, result.pk)
        self.assertFalse(DataVersion.objects.exists())
        self.assertIn('built 1 stock-move records', output.getvalue())

    @patch(_INDUSTRY_VERSION)
    @patch(_MARKET_SNAPSHOT)
    def test_dry_run_does_not_write_results_or_runs(self, snapshot, industry_version):
        snapshot.return_value = self._snapshot()
        industry_version.return_value = INDUSTRY_VERSION

        call_command('build_stock_moves', '--date', '2026-09-08', '--dry-run')

        self.assertFalse(StockMoveResult.objects.using('stock_moves').exists())
        self.assertFalse(StockMoveRun.objects.using('stock_moves').exists())

    @patch(_INDUSTRY_VERSION)
    @patch(_MARKET_SNAPSHOT)
    def test_incomplete_public_data_does_not_publish_result_and_records_failure(
        self, snapshot, industry_version
    ):
        snapshot.side_effect = CompleteMarketDataUnavailable('no complete version')

        with self.assertRaises(CommandError):
            call_command('build_stock_moves', '--date', '2026-09-08')

        self.assertFalse(StockMoveResult.objects.using('stock_moves').exists())
        run = StockMoveRun.objects.using('stock_moves').get()
        self.assertEqual(run.status, StockMoveRun.Status.FAILED)
        self.assertIn('no complete version', run.error_summary)

    @patch(_INDUSTRY_VERSION)
    @patch(_MARKET_SNAPSHOT)
    def test_missing_industry_mapping_fails_without_writing_a_result(
        self, snapshot, industry_version
    ):
        """行业映射缺失时必须整体失败。

        每个结果行都带 ``industries``，若拿不到映射版本就落一份"没有行业信息"
        的结果，读路径会把它当成当天的正式产物，且永远察觉不到它来自哪一版映射。
        宁可失败，也不落半成品。
        """
        snapshot.return_value = self._snapshot()
        industry_version.side_effect = CompleteIndustrySnapshotUnavailable(
            'no complete industry snapshot'
        )

        with self.assertRaises(CommandError) as caught:
            call_command('build_stock_moves', '--date', '2026-09-08')

        self.assertIn('no complete industry snapshot', str(caught.exception))
        self.assertFalse(StockMoveResult.objects.using('stock_moves').exists())
        run = StockMoveRun.objects.using('stock_moves').get()
        self.assertEqual(run.status, StockMoveRun.Status.FAILED)

    @patch(_INDUSTRY_VERSION)
    @patch(_MARKET_SNAPSHOT)
    def test_new_public_data_version_creates_identifiable_rebuilt_result(
        self, snapshot, industry_version
    ):
        snapshot.side_effect = [
            self._snapshot('daily-prices-20260908-v1'),
            self._snapshot('daily-prices-20260908-v2'),
        ]
        industry_version.return_value = INDUSTRY_VERSION

        call_command('build_stock_moves', '--date', '2026-09-08')
        call_command('build_stock_moves', '--date', '2026-09-08')

        self.assertEqual(
            set(StockMoveResult.objects.using('stock_moves').values_list(
                'source_daily_price_version', flat=True
            )),
            {'daily-prices-20260908-v1', 'daily-prices-20260908-v2'},
        )

    @patch(_INDUSTRY_VERSION)
    @patch(_MARKET_SNAPSHOT)
    def test_new_industry_version_creates_identifiable_rebuilt_result(
        self, snapshot, industry_version
    ):
        """只重跑行业映射（行情版本不变）也必须产生一条可识别的新结果。"""
        snapshot.return_value = self._snapshot()
        industry_version.side_effect = [
            'industries-20260908-v1',
            'industries-20260908-v2',
        ]

        call_command('build_stock_moves', '--date', '2026-09-08')
        call_command('build_stock_moves', '--date', '2026-09-08')

        self.assertEqual(
            set(StockMoveResult.objects.using('stock_moves').values_list(
                'source_industry_version', flat=True
            )),
            {'industries-20260908-v1', 'industries-20260908-v2'},
        )
