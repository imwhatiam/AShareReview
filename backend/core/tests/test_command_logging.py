import re
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from core.logging import ProgressReporter, command_logging_context, log_command_progress
from core.services.sync_reference import ReferenceSyncResult


def _command_context(**overrides):
    options = {
        'module_id': 'core',
        'dataset_key': 'stock_master',
        'business_date': None,
        'batch_id': 'batch-1',
        'dry_run': False,
    }
    options.update(overrides)
    return command_logging_context(**options)


def _batch_id(line: str) -> str:
    return re.search(r'batch_id=(\S+)', line).group(1)


class CommandProgressLoggingTests(SimpleTestCase):
    def test_progress_is_silent_when_no_command_is_bound(self):
        with self.assertNoLogs('core.management', level='INFO'):
            self.assertFalse(log_command_progress('stock_master', action='started'))

    def test_progress_carries_the_bound_command_identity(self):
        with _command_context(), self.assertLogs('core.management', level='INFO') as logs:
            self.assertTrue(log_command_progress('stock_master', action='started'))

        rendered = '\n'.join(logs.output)
        self.assertIn('data_command_progress', rendered)
        self.assertIn('module=core', rendered)
        self.assertIn('dataset=stock_master', rendered)
        self.assertIn('business_date=-', rendered)
        self.assertIn('batch_id=batch-1', rendered)
        self.assertIn('dry_run=False', rendered)
        self.assertIn('stage=stock_master', rendered)
        self.assertIn('action=started', rendered)

    def test_progress_is_unbound_again_after_the_context_exits(self):
        with _command_context():
            pass
        self.assertFalse(log_command_progress('stock_master'))

    def test_progress_details_are_redacted_and_kept_on_a_single_line(self):
        with _command_context(), self.assertLogs('core.management', level='INFO') as logs:
            log_command_progress('stock_master', note='token=top-secret\nsecond line')

        self.assertEqual(len(logs.output), 1)
        rendered = logs.output[0]
        self.assertNotIn('top-secret', rendered)
        self.assertIn('[REDACTED]', rendered)
        self.assertIn('note=token=[REDACTED]_second_line', rendered)


class ProgressReporterTests(SimpleTestCase):
    def test_reporter_throttles_between_phase_boundaries(self):
        with _command_context(), self.assertLogs('core.management', level='INFO') as logs:
            progress = ProgressReporter(
                'stock_daily_prices', total=4, min_interval_seconds=3600, phase='fetch'
            )
            progress.start(action='started')
            progress.advance(stock='000001')
            progress.advance(stock='000002')
            progress.report(force=True, action='finished')

        # 阶段开始 + 首次推进 + 强制收尾；中间的第二次推进被节流吃掉。
        self.assertEqual(len(logs.output), 3)
        self.assertIn('phase=fetch', logs.output[0])
        self.assertIn('action=started', logs.output[0])
        self.assertIn('processed=1', logs.output[1])
        self.assertIn('total=4', logs.output[1])
        self.assertIn('percent=25.0', logs.output[1])
        self.assertIn('eta_seconds=', logs.output[1])
        self.assertIn('stock=000001', logs.output[1])
        self.assertIn('processed=2', logs.output[2])
        self.assertIn('action=finished', logs.output[2])

    def test_reporter_omits_percent_and_eta_without_a_known_total(self):
        with _command_context(), self.assertLogs('core.management', level='INFO') as logs:
            progress = ProgressReporter(
                'kaipanla_industry_snapshot', min_interval_seconds=0, parents_total=270
            )
            progress.advance(parent_index=1, industry='通信')

        rendered = logs.output[0]
        self.assertIn('parents_total=270', rendered)
        self.assertIn('processed=1', rendered)
        self.assertIn('parent_index=1', rendered)
        self.assertNotIn('percent=', rendered)
        self.assertNotIn('eta_seconds=', rendered)


class CommandProgressWiringTests(SimpleTestCase):
    def test_command_progress_shares_the_batch_id_with_the_start_event(self):
        def service(*, page_size, dry_run):
            log_command_progress('stock_master', action='fetching_tickers', offset=0)
            return ReferenceSyncResult('stock_master', 1, dry_run)

        with (
            patch('core.services.sync_reference.sync_stock_master', side_effect=service),
            self.assertLogs('core.management', level='INFO') as logs,
        ):
            call_command('sync_stock_master', '--limit', '1', '--dry-run')

        started = next(line for line in logs.output if 'data_command_started' in line)
        finished = next(line for line in logs.output if 'data_command_finished' in line)
        progress = next(line for line in logs.output if 'data_command_progress' in line)

        self.assertEqual(_batch_id(started), _batch_id(progress))
        self.assertEqual(_batch_id(finished), _batch_id(progress))
        self.assertIn('stage=stock_master', progress)
        self.assertIn('offset=0', progress)
        self.assertIn('dry_run=True', progress)


class CommandFailureReportingTests(SimpleTestCase):
    """命令行上必须看得见**具体**原因，而不只是"同步失败"。"""

    def _fail_with(self, error: Exception):
        with patch('core.services.sync_reference.sync_stock_master', side_effect=error):
            with self.assertLogs('core.management', level='ERROR') as logs:
                with self.assertRaises(CommandError) as raised:
                    call_command('sync_stock_master', '--limit', '1')
        return raised.exception, '\n'.join(logs.output)

    def test_the_specific_cause_is_kept_on_the_command_line(self):
        error, rendered = self._fail_with(
            ValueError('The requested date is not in the trading calendar.')
        )

        self.assertIn('Stock master synchronization failed.', str(error))
        self.assertIn('The requested date is not in the trading calendar.', str(error))
        self.assertIn('data_command_failed', rendered)
        self.assertIn('error=The requested date is not in the trading calendar.', rendered)

    def test_a_non_upstream_failure_does_not_claim_an_upstream_error_code(self):
        error, rendered = self._fail_with(ValueError('the calendar is missing'))

        self.assertNotIn('error_code=', rendered)
        self.assertIn('the calendar is missing', str(error))

    def test_a_rate_limited_upstream_is_reachable_by_its_stable_error_code(self):
        from core.integrations.hithink.contracts import HithinkRateLimitError

        error, rendered = self._fail_with(
            HithinkRateLimitError('Hithink REST rate limit exceeded.')
        )

        self.assertIn('error_code=UPSTREAM_RATE_LIMITED', rendered)
        self.assertIn('Hithink REST rate limit exceeded.', str(error))

    def test_credentials_never_reach_the_console_message(self):
        error, _ = self._fail_with(
            ValueError('token=top-secret rejected by the upstream')
        )

        self.assertNotIn('top-secret', str(error))
        self.assertIn('[REDACTED]', str(error))
