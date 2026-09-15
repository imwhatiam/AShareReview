from datetime import date
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from core.models import IndustrySnapshot
from core.services.contracts import (
    CompleteMarketSnapshot,
    MarketPrice,
    Industry,
)
from core.services.market_data import CompleteMarketDataUnavailable
from sector_momentum.models import SectorMomentumRanking

_COMMAND_LOGGER = 'core.management'
_MARKET_SNAPSHOT = (
    'sector_momentum.management.commands.build_sector_momentum.get_complete_market_snapshot'
)


class BuildSectorMomentumCommandTests(TestCase):
    databases = {'default', 'sector_momentum'}
    business_date = date(2026, 9, 8)

    def setUp(self):
        # 行业映射是排行的分组键，命令会先确认它在库里（``require_industry_snapshot``）。
        IndustrySnapshot.objects.create(
            industry_code='I001', industry_name='银行', stock_codes=['600001']
        )

    def _snapshot(self, price_count=1):
        return CompleteMarketSnapshot(
            business_date=self.business_date,
            prices=tuple(
                MarketPrice(
                    stock_code=f'600{number:03d}', thscode=f'600{number:03d}.SH',
                    stock_name=f'股票{number}', exchange='sse', trade_date=self.business_date,
                    pre_close=None, open_price=None, high_price=None, low_price=None,
                    close_price=None, change_percent=Decimal('8'), volume=None,
                    turnover=Decimal('800000000'), has_valid_trade=True,
                )
                for number in range(1, price_count + 1)
            ),
            industries=(Industry('I001', '银行', ('600001',)),),
        )

    @patch(_MARKET_SNAPSHOT)
    def test_writes_only_momentum_records_for_complete_public_sources(self, snapshot):
        snapshot.return_value = self._snapshot()
        output = StringIO()

        call_command('build_sector_momentum', '--date', '2026-09-08', stdout=output)

        ranking = SectorMomentumRanking.objects.using('sector_momentum').get(
            metric=SectorMomentumRanking.Metric.ABOVE_5PCT
        )
        self.assertEqual(ranking.business_date, self.business_date)
        self.assertEqual(ranking.industry_code, 'I001')
        self.assertEqual(ranking.unmapped_stock_count, 0)
        self.assertEqual(
            [stock['code'] for stock in ranking.stocks], ['600001'],
            '明细是名次与五个数值列的唯一来源，必须落库',
        )
        self.assertIn('built 2 sector-momentum rankings', output.getvalue())

    @patch(_MARKET_SNAPSHOT)
    def test_a_rebuild_replaces_the_days_rows_instead_of_adding_them(self, snapshot):
        """同一天重跑是换掉这一天的全部行 —— 结果按业务日期唯一，没有版本号可比。"""
        snapshot.return_value = self._snapshot()

        call_command('build_sector_momentum', '--date', '2026-09-08')
        call_command('build_sector_momentum', '--date', '2026-09-08')

        self.assertEqual(
            SectorMomentumRanking.objects.using('sector_momentum').count(),
            2,
            '两个指标各一条，重跑不能把它们累加成四条',
        )

    @patch(_MARKET_SNAPSHOT)
    def test_a_rebuild_moves_published_at_forward(self, snapshot):
        """发布时间是缓存身份：不前进的话，重跑后 TTL 内还会发上一版报文。"""
        snapshot.return_value = self._snapshot()

        call_command('build_sector_momentum', '--date', '2026-09-08')
        first = SectorMomentumRanking.objects.using('sector_momentum').first().published_at
        call_command('build_sector_momentum', '--date', '2026-09-08')
        second = SectorMomentumRanking.objects.using('sector_momentum').first().published_at

        self.assertGreater(second, first)

    @patch(_MARKET_SNAPSHOT)
    def test_dry_run_does_not_write_results_or_rankings(self, snapshot):
        snapshot.return_value = self._snapshot()

        call_command('build_sector_momentum', '--date', '2026-09-08', '--dry-run')

        self.assertFalse(SectorMomentumRanking.objects.using('sector_momentum').exists())

    @patch(_MARKET_SNAPSHOT)
    def test_missing_complete_public_source_writes_nothing_and_logs_the_failure(self, snapshot):
        snapshot.side_effect = CompleteMarketDataUnavailable('No daily prices are stored.')

        with self.assertLogs(_COMMAND_LOGGER, level='ERROR') as captured:
            with self.assertRaises(CommandError):
                call_command('build_sector_momentum', '--date', '2026-09-08')

        self.assertFalse(SectorMomentumRanking.objects.using('sector_momentum').exists())
        self.assertIn('data_command_failed', '\n'.join(captured.output))

    @patch(_MARKET_SNAPSHOT)
    def test_missing_industry_mapping_fails_without_writing_a_result(self, snapshot):
        """没有行业映射就没有分组键：宁可失败，也不落一份空排行的结果。"""
        IndustrySnapshot.objects.all().delete()
        snapshot.return_value = self._snapshot()

        with self.assertRaises(CommandError) as caught:
            call_command('build_sector_momentum', '--date', '2026-09-08')

        self.assertIn('No Kaipanla industry snapshot is stored.', str(caught.exception))
        self.assertFalse(SectorMomentumRanking.objects.using('sector_momentum').exists())
