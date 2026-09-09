from datetime import datetime
from decimal import Decimal
from io import StringIO
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from core.models import DataVersion, TradingDay
from kaipanla.services.fetcher import KaipanlaSectorFundFlowFetchResult
from kaipanla.services.parser import KaipanlaSectorFundFlowRow


class KaipanlaSectorFundFlowCommandTests(TestCase):
    databases = {'default', 'kaipanla'}

    def setUp(self):
        self.snapshot_time = timezone.make_aware(datetime(2026, 9, 8, 10, 5))
        self.complete_result = KaipanlaSectorFundFlowFetchResult(
            rows=(
                KaipanlaSectorFundFlowRow(
                    sector_code='BK001', sector_name='半导体', change_pct=Decimal('1.2'),
                    main_net_inflow=Decimal('20'), main_buy=Decimal('30'), main_sell=Decimal('10'),
                    large_order_net_inflow=Decimal('4'), volume_ratio=Decimal('1.1'),
                    turnover_amount=Decimal('100'), float_market_cap=Decimal('50'),
                    total_market_cap=Decimal('60'),
                ),
            ),
            is_complete=True,
            expected_page_count=1,
            completed_page_count=1,
            failed_page_offsets=(),
            source_timestamp=int(self.snapshot_time.timestamp()),
            source_trade_date='2026-09-08',
        )

    @patch('kaipanla.management.commands.fetch_kaipanla_sector_fund_flow.KaipanlaSectorFundFlowFetcher')
    def test_latest_complete_fetch_writes_then_publishes_a_version(self, fetcher_class):
        fetcher_class.return_value.fetch.return_value = self.complete_result

        output = StringIO()
        call_command('fetch_kaipanla_sector_fund_flow', '--latest', stdout=output)

        from kaipanla.models import KaipanlaSectorFundFlowRun, KaipanlaSectorFundFlowSnapshot

        self.assertEqual(KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').count(), 1)
        self.assertEqual(
            KaipanlaSectorFundFlowRun.objects.using('kaipanla').get().status,
            KaipanlaSectorFundFlowRun.Status.COMPLETE,
        )
        version = DataVersion.objects.get(dataset_key='kaipanla_sector_fund_flow')
        self.assertEqual(version.status, DataVersion.Status.COMPLETE)
        self.assertIn('published 1', output.getvalue())

    @patch('kaipanla.management.commands.fetch_kaipanla_sector_fund_flow.default_file_cache')
    @patch('kaipanla.management.commands.fetch_kaipanla_sector_fund_flow.KaipanlaSectorFundFlowFetcher')
    def test_success_invalidates_only_the_kaipanla_cache_after_publication(self, fetcher_class, cache_factory):
        fetcher_class.return_value.fetch.return_value = self.complete_result
        cache = Mock()
        cache_factory.return_value = cache

        call_command('fetch_kaipanla_sector_fund_flow', '--latest')

        cache.invalidate_module.assert_called_once_with('kaipanla')

    @patch('kaipanla.management.commands.fetch_kaipanla_sector_fund_flow.KaipanlaSectorFundFlowFetcher')
    def test_incomplete_fetch_fails_without_replacing_an_existing_snapshot(self, fetcher_class):
        from kaipanla.models import KaipanlaSectorFundFlowSnapshot

        KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').create(
            sector_code='OLD', sector_name='旧快照', trade_date=self.snapshot_time.date(),
            snapshot_time=self.snapshot_time, main_net_inflow=Decimal('1'), source_batch_id='old',
        )
        fetcher_class.return_value.fetch.return_value = KaipanlaSectorFundFlowFetchResult(
            rows=(), is_complete=False, expected_page_count=2, completed_page_count=1,
            failed_page_offsets=(80,), source_timestamp=int(self.snapshot_time.timestamp()),
            source_trade_date='2026-09-08', error_summary='A required page failed.',
        )

        with self.assertRaises(CommandError):
            call_command('fetch_kaipanla_sector_fund_flow', '--latest')

        self.assertEqual(KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').count(), 1)
        self.assertEqual(KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').get().sector_code, 'OLD')
        self.assertFalse(DataVersion.objects.filter(dataset_key='kaipanla_sector_fund_flow').exists())

    @patch('kaipanla.management.commands.fetch_kaipanla_sector_fund_flow.KaipanlaSectorFundFlowFetcher')
    def test_dry_run_never_writes_snapshots_runs_or_versions(self, fetcher_class):
        fetcher_class.return_value.fetch.return_value = self.complete_result

        call_command('fetch_kaipanla_sector_fund_flow', '--latest', '--dry-run')

        from kaipanla.models import KaipanlaSectorFundFlowRun, KaipanlaSectorFundFlowSnapshot

        self.assertFalse(KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').exists())
        self.assertFalse(KaipanlaSectorFundFlowRun.objects.using('kaipanla').exists())
        self.assertFalse(DataVersion.objects.filter(dataset_key='kaipanla_sector_fund_flow').exists())

    def test_default_mode_requires_a_calendar_trading_day(self):
        from kaipanla.management.commands.fetch_kaipanla_sector_fund_flow import Command

        weekday_morning = timezone.make_aware(datetime(2026, 9, 8, 10, 0))

        self.assertFalse(Command._is_trading_session(weekday_morning))

        TradingDay.objects.create(trade_date=weekday_morning.date())

        self.assertTrue(Command._is_trading_session(weekday_morning))
        self.assertFalse(
            Command._is_trading_session(
                timezone.make_aware(datetime(2026, 9, 8, 12, 0))
            )
        )
