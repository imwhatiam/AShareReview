from datetime import date
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from core.models import IndustrySnapshot
from core.services.contracts import CompleteMarketSnapshot, MarketPrice, Industry
from core.services.market_data import CompleteMarketDataUnavailable
from stock_moves.models import StockMoveItem

_COMMAND_LOGGER = 'core.management'
_MARKET_SNAPSHOT = 'stock_moves.management.commands.build_stock_moves.get_complete_market_snapshot'


class BuildStockMovesCommandTests(TestCase):
    databases = {'default', 'stock_moves'}
    business_date = date(2026, 9, 8)

    def setUp(self):
        # 行业映射是第二个输入，命令会先确认它在库里（``require_industry_snapshot``）。
        IndustrySnapshot.objects.create(
            industry_code='I001', industry_name='银行', stock_codes=['600001']
        )

    def _snapshot(self, price_count=1):
        return CompleteMarketSnapshot(
            business_date=self.business_date,
            prices=tuple(
                MarketPrice(
                    stock_code=f'600{number:03d}',
                    thscode=f'600{number:03d}.SH',
                    stock_name=f'股票{number}',
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
                )
                for number in range(1, price_count + 1)
            ),
            industries=(Industry('I001', '银行', ('600001',)),),
        )

    @patch(_MARKET_SNAPSHOT)
    def test_writes_only_derived_stock_moves_records_for_complete_market_snapshot(
        self, snapshot
    ):
        snapshot.return_value = self._snapshot()
        output = StringIO()

        call_command('build_stock_moves', '--date', '2026-09-08', stdout=output)

        item = StockMoveItem.objects.using('stock_moves').get()
        self.assertEqual(item.business_date, self.business_date)
        self.assertEqual(item.group, StockMoveItem.Group.SSE_RISE)
        self.assertEqual(item.rank, 1)
        # 行业映射来自库里那一行，写进明细行后读路径直接拿来用。
        self.assertEqual(item.industries, [{'code': 'I001', 'name': '银行'}])
        self.assertIn('built 1 stock-move records', output.getvalue())

    @patch(_MARKET_SNAPSHOT)
    def test_a_rebuild_replaces_the_days_rows_instead_of_adding_them(self, snapshot):
        """同一天重跑是换掉这一天的全部行 —— 结果按业务日期唯一，没有版本号可比。"""
        snapshot.side_effect = [self._snapshot(1), self._snapshot(2)]

        call_command('build_stock_moves', '--date', '2026-09-08')
        call_command('build_stock_moves', '--date', '2026-09-08')

        items = StockMoveItem.objects.using('stock_moves').filter(
            business_date=self.business_date
        )
        self.assertEqual(items.count(), 2)
        self.assertEqual(
            sorted(items.values_list('rank', flat=True)), [1, 2],
            '重跑不能把两批股票累加成三行',
        )

    @patch(_MARKET_SNAPSHOT)
    def test_a_rebuild_moves_published_at_forward(self, snapshot):
        """发布时间是缓存身份：不前进的话，重跑后 TTL 内还会发上一版报文。"""
        snapshot.side_effect = [self._snapshot(1), self._snapshot(2)]

        call_command('build_stock_moves', '--date', '2026-09-08')
        first = StockMoveItem.objects.using('stock_moves').first().published_at
        call_command('build_stock_moves', '--date', '2026-09-08')
        second = StockMoveItem.objects.using('stock_moves').first().published_at

        self.assertGreater(second, first)

    @patch(_MARKET_SNAPSHOT)
    def test_dry_run_does_not_write_results_or_items(self, snapshot):
        snapshot.return_value = self._snapshot()

        call_command('build_stock_moves', '--date', '2026-09-08', '--dry-run')

        self.assertFalse(StockMoveItem.objects.using('stock_moves').exists())

    @patch(_MARKET_SNAPSHOT)
    def test_incomplete_public_data_writes_nothing_and_logs_the_failure(self, snapshot):
        snapshot.side_effect = CompleteMarketDataUnavailable('No daily prices are stored.')

        with self.assertLogs(_COMMAND_LOGGER, level='ERROR') as captured:
            with self.assertRaises(CommandError):
                call_command('build_stock_moves', '--date', '2026-09-08')

        self.assertFalse(StockMoveItem.objects.using('stock_moves').exists())
        logged = '\n'.join(captured.output)
        self.assertIn('data_command_failed', logged)
        self.assertIn('dataset=stock_moves', logged)

    @patch(_MARKET_SNAPSHOT)
    def test_missing_industry_mapping_fails_without_writing_a_result(self, snapshot):
        """行业映射缺失时必须整体失败。

        每个结果行都带 ``industries``，拿不到映射就只能落一份"没有行业信息"的结果，
        读路径会把它当成当天的正式产物。宁可失败，也不落半成品。
        """
        IndustrySnapshot.objects.all().delete()
        snapshot.return_value = self._snapshot()

        with self.assertRaises(CommandError) as caught:
            call_command('build_stock_moves', '--date', '2026-09-08')

        self.assertIn('No Kaipanla industry snapshot is stored.', str(caught.exception))
        self.assertFalse(StockMoveItem.objects.using('stock_moves').exists())
