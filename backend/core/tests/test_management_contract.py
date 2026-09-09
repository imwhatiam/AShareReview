from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase

from core.services.locking import DatasetLocked
from core.services.sync_reference import ReferenceSyncResult


class ManagementCommandContractTests(SimpleTestCase):
    def test_public_commands_reject_an_active_dataset_lock_before_calling_services(self):
        commands = (
            (
                'sync_stock_master',
                ('--limit', '1'),
                'core.services.sync_reference.sync_stock_master',
            ),
            (
                'sync_trading_calendar',
                (),
                'core.services.sync_reference.sync_trading_calendar',
            ),
            (
                'sync_kaipanla_industry_snapshot',
                (),
                'core.services.sync_industries.sync_kaipanla_industry_snapshot',
            ),
            (
                'init_stock_daily_prices',
                ('--years', '1'),
                'core.services.sync_daily_prices.initialize_stock_daily_prices',
            ),
            (
                'sync_stock_daily_prices',
                ('--date', '2026-09-08'),
                'core.services.sync_daily_prices.sync_stock_daily_prices',
            ),
        )

        for command_name, arguments, service_path in commands:
            with self.subTest(command=command_name):
                with (
                    patch(
                        'core.management.base.dataset_lock',
                        side_effect=DatasetLocked('core:test is already running.'),
                    ),
                    patch(service_path) as service,
                    self.assertRaises(CommandError),
                ):
                    call_command(command_name, *arguments)

                service.assert_not_called()

    def test_failure_logs_redact_sensitive_values_and_include_command_context(self):
        with (
            patch(
                'core.services.sync_reference.sync_stock_master',
                side_effect=RuntimeError(
                    'upstream rejected api_key=top-secret token=also-secret '
                    'device_id=device-secret'
                ),
            ),
            self.assertLogs('core.management', level='ERROR') as logs,
            self.assertRaises(CommandError),
        ):
            call_command('sync_stock_master', '--limit', '1')

        rendered = '\n'.join(logs.output)
        self.assertIn('module=core', rendered)
        self.assertIn('dataset=stock_master', rendered)
        self.assertIn('batch_id=', rendered)
        self.assertNotIn('top-secret', rendered)
        self.assertNotIn('also-secret', rendered)
        self.assertNotIn('device-secret', rendered)
        self.assertIn('[REDACTED]', rendered)

    def test_success_logs_duration_and_dry_run_context(self):
        with (
            patch(
                'core.services.sync_reference.sync_stock_master',
                return_value=ReferenceSyncResult('stock_master', 1, True),
            ),
            self.assertLogs('core.management', level='INFO') as logs,
        ):
            output = StringIO()
            call_command('sync_stock_master', '--limit', '1', '--dry-run', stdout=output)

        self.assertIn('dry-run', output.getvalue())
        rendered = '\n'.join(logs.output)
        self.assertIn('module=core', rendered)
        self.assertIn('dataset=stock_master', rendered)
        self.assertIn('dry_run=True', rendered)
        self.assertIn('duration_seconds=', rendered)
        self.assertIn('batch_id=', rendered)


class ManagementCommandRunStatusTests(TestCase):
    def test_successful_command_clears_the_prior_consecutive_failure_count(self):
        from core.integrations.hithink.contracts import HithinkTicker
        from core.models import ModuleRunStatus

        class SuccessfulHithinkClient:
            def list_a_share_tickers(self, *, limit, offset):
                if offset:
                    return ()
                return (HithinkTicker('000001.SZ', '000001', '平安银行', 'szse'),)

        ModuleRunStatus.objects.create(
            module_id='core',
            dataset_key='stock_master',
            status=ModuleRunStatus.Status.FAILED,
            completeness='failed',
            serving_stale=True,
            consecutive_failure_count=3,
            error_summary='old failure',
        )

        with patch(
            'core.services.sync_reference.HithinkClient',
            return_value=SuccessfulHithinkClient(),
        ):
            call_command('sync_stock_master', '--limit', '1')

        status = ModuleRunStatus.objects.get(module_id='core', dataset_key='stock_master')
        self.assertEqual(status.status, ModuleRunStatus.Status.SUCCESS)
        self.assertEqual(status.consecutive_failure_count, 0)
