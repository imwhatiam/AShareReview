from datetime import date, datetime
from decimal import Decimal
from unittest.mock import Mock, patch

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from core.models import DataVersion, ModuleRunStatus
from eastmoney.models import EastmoneySectorFundFlowRun, EastmoneySectorFundFlowSnapshot
from eastmoney.services.fetcher import (
    EastmoneyDirectionFetchResult,
    EastmoneySectorFundFlowFetchResult,
)


class FetchEastmoneySectorFundFlowCommandTests(TestCase):
    databases = {'default', 'eastmoney'}

    @patch('eastmoney.management.commands.fetch_eastmoney_sector_fund_flow.default_file_cache')
    @patch('eastmoney.management.commands.fetch_eastmoney_sector_fund_flow.EastmoneySectorFundFlowFetcher')
    def test_complete_result_publishes_version_then_invalidates_only_eastmoney_cache(
        self, fetcher_class, cache_factory
    ):
        fetcher_class.return_value.fetch.return_value = _complete_result()
        cache = Mock()
        cache_factory.return_value = cache

        call_command('fetch_eastmoney_sector_fund_flow', '--latest')

        version = DataVersion.objects.get(dataset_key='eastmoney_sector_fund_flow')
        self.assertEqual(version.status, DataVersion.Status.COMPLETE)
        self.assertEqual(EastmoneySectorFundFlowSnapshot.objects.using('eastmoney').count(), 2)
        cache.invalidate_module.assert_called_once_with('eastmoney')

    @patch('eastmoney.management.commands.fetch_eastmoney_sector_fund_flow.EastmoneySectorFundFlowFetcher')
    def test_partial_result_publishes_partial_version_and_direction_status(self, fetcher_class):
        fetcher_class.return_value.fetch.return_value = _partial_result()

        call_command('fetch_eastmoney_sector_fund_flow', '--latest')

        version = DataVersion.objects.get(dataset_key='eastmoney_sector_fund_flow')
        run = EastmoneySectorFundFlowRun.objects.using('eastmoney').get()
        self.assertEqual(version.status, DataVersion.Status.PARTIAL)
        self.assertEqual(version.missing_record_count, 1)
        self.assertEqual(run.status, EastmoneySectorFundFlowRun.Status.PARTIAL)
        self.assertEqual(run.outflow_status, EastmoneySectorFundFlowRun.DirectionStatus.FAILED)

    @patch('eastmoney.management.commands.fetch_eastmoney_sector_fund_flow.EastmoneySectorFundFlowFetcher')
    def test_double_upstream_failure_keeps_old_data_and_does_not_publish(self, fetcher_class):
        EastmoneySectorFundFlowSnapshot.objects.using('eastmoney').create(
            sector_code='OLD',
            sector_name='旧数据',
            trade_date=date(2026, 9, 8),
            snapshot_time=timezone.make_aware(datetime(2026, 9, 8, 15, 0)),
            main_net_inflow=Decimal('1'),
            source_batch_id='old-batch',
        )
        fetcher_class.return_value.fetch.return_value = _failed_result()

        with self.assertRaises(CommandError):
            call_command('fetch_eastmoney_sector_fund_flow', '--latest')

        self.assertEqual(EastmoneySectorFundFlowSnapshot.objects.using('eastmoney').count(), 1)
        self.assertFalse(DataVersion.objects.filter(dataset_key='eastmoney_sector_fund_flow').exists())
        self.assertEqual(
            EastmoneySectorFundFlowRun.objects.using('eastmoney').get(
                source_batch_id__isnull=False
            ).status,
            EastmoneySectorFundFlowRun.Status.FAILED,
        )
        status = ModuleRunStatus.objects.get(
            module_id='eastmoney', dataset_key='eastmoney_sector_fund_flow'
        )
        self.assertEqual(status.status, ModuleRunStatus.Status.FAILED)

    @patch('eastmoney.management.commands.fetch_eastmoney_sector_fund_flow.EastmoneySectorFundFlowFetcher')
    def test_dry_run_never_writes_snapshots_runs_or_versions(self, fetcher_class):
        fetcher_class.return_value.fetch.return_value = _complete_result()

        call_command('fetch_eastmoney_sector_fund_flow', '--latest', '--dry-run')

        self.assertFalse(EastmoneySectorFundFlowSnapshot.objects.using('eastmoney').exists())
        self.assertFalse(EastmoneySectorFundFlowRun.objects.using('eastmoney').exists())
        self.assertFalse(DataVersion.objects.filter(dataset_key='eastmoney_sector_fund_flow').exists())


def _complete_result():
    inflow = EastmoneyDirectionFetchResult('inflow', (_row('BK001', '10'),), True)
    outflow = EastmoneyDirectionFetchResult('outflow', (_row('BK002', '-10'),), True)
    return EastmoneySectorFundFlowFetchResult(inflow.rows + outflow.rows, inflow, outflow)


def _partial_result():
    inflow = EastmoneyDirectionFetchResult('inflow', (_row('BK001', '10'),), True)
    outflow = EastmoneyDirectionFetchResult('outflow', (), False, 'HTTP 403 blocked by upstream.')
    return EastmoneySectorFundFlowFetchResult(inflow.rows, inflow, outflow)


def _failed_result():
    inflow = EastmoneyDirectionFetchResult('inflow', (), False, 'HTTP 403 blocked by upstream.')
    outflow = EastmoneyDirectionFetchResult('outflow', (), False, 'HTTP 403 blocked by upstream.')
    return EastmoneySectorFundFlowFetchResult((), inflow, outflow)


def _row(sector_code, main_net_inflow):
    return {
        'sector_code': sector_code,
        'sector_name': sector_code,
        'latest_index': Decimal('100'),
        'change_pct': Decimal('1'),
        'main_net_inflow': Decimal(main_net_inflow),
        'main_net_inflow_ratio': Decimal('1'),
        'super_large_net_inflow': Decimal('1'),
        'large_net_inflow': Decimal('1'),
        'medium_net_inflow': Decimal('1'),
        'small_net_inflow': Decimal('1'),
    }
