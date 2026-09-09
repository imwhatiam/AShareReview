"""Shared execution contract for bounded data-management commands."""

import logging
from time import perf_counter
from uuid import uuid4

from django.core.management.base import BaseCommand, CommandError

from core.logging import log_command_event
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
            )
            raise CommandError(self.failure_message) from error

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
