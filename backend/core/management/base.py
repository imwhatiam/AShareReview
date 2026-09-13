"""Shared execution contract for bounded data-management commands."""

import logging
from time import perf_counter
from uuid import uuid4

from django.core.management.base import BaseCommand, CommandError

from core.api.errors import upstream_error_code_value
from core.logging import command_logging_context, log_command_event, redact_sensitive_text
from core.services.locking import DatasetLocked, dataset_lock


class BaseDataCommand(BaseCommand):
    """Add locking and safe lifecycle logging without owning business logic."""

    module_id = 'core'
    dataset_key = ''
    failure_message = 'Data synchronization failed.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def get_business_date(self, options):
        return options.get('date')

    def run_data_sync(self, options):
        raise NotImplementedError

    def format_success_message(self, result, options) -> str:
        raise NotImplementedError

    def _failure_message_for(self, error: Exception) -> str:
        """Keep the specific reason on the terminal instead of only in the log.

        The operator reads this line in the terminal or in a crontab mail, where
        ``Data synchronization failed.`` alone is unusable: the actual cause
        (``The requested date is not in the trading calendar.``) used to be
        written only to the log file. The original message is redacted first, so
        a credential that somehow ended up in it cannot leak into a console.
        """
        detail = redact_sensitive_text(error).strip()
        if not detail or detail == self.failure_message:
            return self.failure_message
        return f'{self.failure_message} Cause: {detail}'

    def handle(self, *args, **options):
        if not self.dataset_key:
            raise CommandError('Data command must declare a dataset key.')

        batch_id = uuid4().hex
        dry_run = options['dry_run']
        business_date = self.get_business_date(options)
        started_at = perf_counter()
        log_command_event(
            logging.INFO,
            'data_command_started',
            module_id=self.module_id,
            dataset_key=self.dataset_key,
            business_date=business_date,
            batch_id=batch_id,
            dry_run=dry_run,
        )
        try:
            # 绑定批次身份后，run_data_sync 内部各层（服务、客户端、分页循环）
            # 都能直接发进度日志，不必把 module_id/batch_id 一路透传。
            with command_logging_context(
                module_id=self.module_id,
                dataset_key=self.dataset_key,
                business_date=business_date,
                batch_id=batch_id,
                dry_run=dry_run,
            ):
                with dataset_lock(self.module_id, self.dataset_key):
                    result = self.run_data_sync(options)
        except DatasetLocked:
            duration_seconds = perf_counter() - started_at
            log_command_event(
                logging.WARNING,
                'data_command_locked',
                module_id=self.module_id,
                dataset_key=self.dataset_key,
                business_date=business_date,
                batch_id=batch_id,
                dry_run=dry_run,
                duration_seconds=duration_seconds,
            )
            raise CommandError('A synchronization for this dataset is already running.')
        except Exception as error:
            duration_seconds = perf_counter() - started_at
            log_command_event(
                logging.ERROR,
                'data_command_failed',
                module_id=self.module_id,
                dataset_key=self.dataset_key,
                business_date=business_date,
                batch_id=batch_id,
                dry_run=dry_run,
                duration_seconds=duration_seconds,
                error=error,
                # 「上游限流 / 上游不可用」在日志里可筛：稳定错误码与 HTTP 契约同一套
                # 拼写，非上游类失败留空，不误标。
                error_code=upstream_error_code_value(error),
            )
            raise CommandError(self._failure_message_for(error)) from error

        duration_seconds = perf_counter() - started_at
        log_command_event(
            logging.INFO,
            'data_command_finished',
            module_id=self.module_id,
            dataset_key=self.dataset_key,
            business_date=business_date,
            batch_id=batch_id,
            dry_run=dry_run,
            duration_seconds=duration_seconds,
        )
        self.stdout.write(self.format_success_message(result, options))
