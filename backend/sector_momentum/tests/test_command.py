from datetime import date
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from core.models import DataVersion
from core.services.contracts import (
    CompleteMarketSnapshot,
    MarketDataVersion,
    MarketPrice,
    ParentIndustry,
)
from core.services.market_data import CompleteMarketDataUnavailable
from sector_momentum.models import (
    SectorMomentumRanking,
    SectorMomentumResult,
    SectorMomentumRun,
)


class BuildSectorMomentumCommandTests(TestCase):
    databases = {'default', 'sector_momentum'}
    business_date = date(2026, 9, 8)

    def _snapshot(self, version='daily-prices-20260908-v1'):
        return CompleteMarketSnapshot(
            data_version=MarketDataVersion(version=version, business_date=self.business_date),
            prices=(
                MarketPrice(
                    stock_code='600001', thscode='600001.SH', stock_name='上涨股票',
                    exchange='sse', trade_date=self.business_date,
                    pre_close=None, open_price=None, high_price=None, low_price=None,
                    close_price=None, change_percent=Decimal('8'), volume=None,
                    turnover=Decimal('800000000'), has_valid_trade=True,
                ),
            ),
            parent_industries=(ParentIndustry('I001', '银行', ('600001',)),),
        )

    def _industry_version(self, version='industry-v1'):
        return DataVersion.objects.create(
            dataset_key='industry_snapshot',
            version=version,
            business_date=self.business_date,
            status=DataVersion.Status.COMPLETE,
            expected_record_count=1,
            actual_record_count=1,
        )

    @patch('sector_momentum.management.commands.build_sector_momentum.get_complete_market_snapshot')
    def test_writes_only_momentum_records_for_complete_public_sources(self, snapshot):
        snapshot.return_value = self._snapshot()
        self._industry_version()
        output = StringIO()

        call_command('build_sector_momentum', '--date', '2026-09-08', stdout=output)

        result = SectorMomentumResult.objects.using('sector_momentum').get()
        ranking = SectorMomentumRanking.objects.using('sector_momentum').get(
            metric=SectorMomentumRanking.Metric.ABOVE_5PCT
        )
        run = SectorMomentumRun.objects.using('sector_momentum').get()
        self.assertEqual(result.source_daily_price_version, 'daily-prices-20260908-v1')
        self.assertEqual(result.source_industry_version, 'industry-v1')
        self.assertEqual(ranking.industry_code, 'I001')
        self.assertEqual(run.status, SectorMomentumRun.Status.SUCCESS)
        self.assertEqual(run.published_result_id, result.pk)
        self.assertIn('built 2 sector-momentum rankings', output.getvalue())

    @patch('sector_momentum.management.commands.build_sector_momentum.get_complete_market_snapshot')
    def test_dry_run_does_not_write_results_or_runs(self, snapshot):
        snapshot.return_value = self._snapshot()
        self._industry_version()

        call_command('build_sector_momentum', '--date', '2026-09-08', '--dry-run')

        self.assertFalse(SectorMomentumResult.objects.using('sector_momentum').exists())
        self.assertFalse(SectorMomentumRun.objects.using('sector_momentum').exists())

    @patch('sector_momentum.management.commands.build_sector_momentum.get_complete_market_snapshot')
    def test_missing_complete_public_source_does_not_publish_and_records_failure(self, snapshot):
        snapshot.side_effect = CompleteMarketDataUnavailable('no complete price version')

        with self.assertRaises(CommandError):
            call_command('build_sector_momentum', '--date', '2026-09-08')

        self.assertFalse(SectorMomentumResult.objects.using('sector_momentum').exists())
        run = SectorMomentumRun.objects.using('sector_momentum').get()
        self.assertEqual(run.status, SectorMomentumRun.Status.FAILED)
        self.assertIn('no complete price version', run.error_summary)

    @patch('sector_momentum.management.commands.build_sector_momentum.get_complete_market_snapshot')
    def test_new_source_version_creates_identifiable_rebuilt_result(self, snapshot):
        snapshot.side_effect = [
            self._snapshot('daily-prices-v1'), self._snapshot('daily-prices-v2'),
        ]
        self._industry_version('industry-v1')

        call_command('build_sector_momentum', '--date', '2026-09-08')
        call_command('build_sector_momentum', '--date', '2026-09-08')

        self.assertEqual(
            set(SectorMomentumResult.objects.using('sector_momentum').values_list(
                'source_daily_price_version', flat=True
            )),
            {'daily-prices-v1', 'daily-prices-v2'},
        )
