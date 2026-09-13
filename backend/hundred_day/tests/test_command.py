from datetime import date, timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from core.services.contracts import MarketDataVersion, Industry
from core.services.market_data import CompleteMarketDataUnavailable
from hundred_day.models import (
    HundredDayIndustrySummary,
    HundredDayResult,
    HundredDayRun,
    HundredDayStockFlag,
    HundredDayTrend,
)
from hundred_day.services.analysis import (
    HistoricalCloseData,
    InsufficientHundredDayHistory,
    TargetDayQuote,
)


class BuildHundredDayCommandTests(TestCase):
    databases = {'default', 'hundred_day'}
    business_date = date(2026, 9, 8)

    def _source(self, version='daily-prices-v1', positions=100):
        days = tuple(
            self.business_date - timedelta(days=positions - index - 1)
            for index in range(positions)
        )
        return HistoricalCloseData(
            data_version=MarketDataVersion(version, self.business_date),
            trading_days=days,
            close_prices_by_stock={
                '600001': {day: Decimal('10') for day in days[:-1]} | {days[-1]: Decimal('11')},
            },
            stock_names_by_code={'600001': '上涨股票'},
            industries=(Industry('I001', '电子', ('600001',)),),
            target_day_quotes={'600001': TargetDayQuote(Decimal('10'), Decimal('1000000'))},
        )

    @patch('hundred_day.management.commands.build_hundred_day.get_complete_industry_snapshot_version')
    @patch('hundred_day.management.commands.build_hundred_day.load_hundred_day_source_data')
    def test_publishes_stock_industry_and_trend_records_from_local_public_data(self, source, industry_version):
        source.return_value = self._source()
        industry_version.return_value = 'industries-v1'
        output = StringIO()

        call_command('build_hundred_day', '--date', '2026-09-08', stdout=output)

        result = HundredDayResult.objects.using('hundred_day').get()
        self.assertEqual(result.source_daily_price_version, 'daily-prices-v1')
        self.assertEqual(result.source_industry_version, 'industries-v1')
        self.assertEqual(result.valid_stock_count, 1)
        self.assertEqual(HundredDayStockFlag.objects.using('hundred_day').count(), 1)
        self.assertEqual(HundredDayIndustrySummary.objects.using('hundred_day').get().new_high_count, 1)
        self.assertEqual(HundredDayTrend.objects.using('hundred_day').count(), 1)
        run = HundredDayRun.objects.using('hundred_day').get()
        self.assertEqual(run.status, HundredDayRun.Status.SUCCESS)
        self.assertEqual(run.published_result_id, result.pk)
        self.assertIn('built 1 hundred-day stock flags', output.getvalue())

    @patch('hundred_day.management.commands.build_hundred_day.get_complete_industry_snapshot_version')
    @patch('hundred_day.management.commands.build_hundred_day.load_hundred_day_source_data')
    def test_dry_run_does_not_write_results_or_runs(self, source, industry_version):
        source.return_value = self._source()
        industry_version.return_value = 'industries-v1'

        call_command('build_hundred_day', '--date', '2026-09-08', '--dry-run')

        self.assertFalse(HundredDayResult.objects.using('hundred_day').exists())
        self.assertFalse(HundredDayRun.objects.using('hundred_day').exists())

    @patch('hundred_day.management.commands.build_hundred_day.load_hundred_day_source_data')
    def test_missing_complete_local_public_data_does_not_publish_and_records_failure(self, source):
        source.side_effect = CompleteMarketDataUnavailable('no complete price version')

        with self.assertRaises(CommandError):
            call_command('build_hundred_day', '--date', '2026-09-08')

        self.assertFalse(HundredDayResult.objects.using('hundred_day').exists())
        run = HundredDayRun.objects.using('hundred_day').get()
        self.assertEqual(run.status, HundredDayRun.Status.FAILED)
        self.assertIn('no complete price version', run.error_summary)

    @patch('hundred_day.management.commands.build_hundred_day.get_complete_industry_snapshot_version')
    @patch('hundred_day.management.commands.build_hundred_day.load_hundred_day_source_data')
    def test_insufficient_history_does_not_publish_and_records_failure(self, source, industry_version):
        source.return_value = self._source(positions=99)
        industry_version.return_value = 'industries-v1'

        with self.assertRaises(CommandError):
            call_command('build_hundred_day', '--date', '2026-09-08')

        run = HundredDayRun.objects.using('hundred_day').get()
        self.assertEqual(run.status, HundredDayRun.Status.FAILED)
        self.assertIn('requires at least 100', run.error_summary)

    @patch('hundred_day.management.commands.build_hundred_day.get_complete_industry_snapshot_version')
    @patch('hundred_day.management.commands.build_hundred_day.load_hundred_day_source_data')
    def test_new_daily_price_version_creates_identifiable_rebuilt_result(self, source, industry_version):
        source.side_effect = [self._source('daily-prices-v1'), self._source('daily-prices-v2')]
        industry_version.return_value = 'industries-v1'

        call_command('build_hundred_day', '--date', '2026-09-08')
        call_command('build_hundred_day', '--date', '2026-09-08')

        self.assertEqual(
            set(HundredDayResult.objects.using('hundred_day').values_list(
                'source_daily_price_version', flat=True
            )),
            {'daily-prices-v1', 'daily-prices-v2'},
        )
