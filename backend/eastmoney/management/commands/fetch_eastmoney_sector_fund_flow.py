"""Fetch and publish one independent Eastmoney sector fund-flow snapshot."""

from datetime import time
from zoneinfo import ZoneInfo

from django.utils import timezone

from core.management.base import BaseDataCommand
from core.models import TradingDay
from core.services.file_cache import default_file_cache
from core.services.publication import begin_publication, fail_publication, finish_publication
from core.services.run_status import mark_failed
from eastmoney.services.fetcher import EastmoneySectorFundFlowFetcher
from eastmoney.services.writer import (
    UnpublishableEastmoneySnapshot,
    new_source_batch_id,
    record_unpublishable_snapshot,
    write_publishable_snapshot,
)

SHANGHAI_TIME_ZONE = ZoneInfo('Asia/Shanghai')


class Command(BaseDataCommand):
    help = 'Fetch and publish an Eastmoney sector fund-flow snapshot.'
    module_id = 'eastmoney'
    dataset_key = 'eastmoney_sector_fund_flow'
    failure_message = 'Eastmoney sector fund-flow synchronization failed.'

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            '--latest',
            action='store_true',
            help='Allow collection outside the normal A-share trading session.',
        )

    def run_data_sync(self, options):
        now = timezone.localtime(timezone.now(), SHANGHAI_TIME_ZONE)
        if not options['latest'] and not self._is_trading_session(now):
            raise ValueError('The default mode is only available during an A-share trading session.')

        fetch_result = EastmoneySectorFundFlowFetcher().fetch()
        snapshot_time = self._snapshot_time(now)
        if options['dry_run']:
            if not fetch_result.has_publishable_rows:
                raise UnpublishableEastmoneySnapshot('Eastmoney returned no publishable sector rows.')
            return {
                'record_count': len(fetch_result.rows),
                'partial': self._missing_direction_count(fetch_result) > 0,
                'dry_run': True,
            }

        source_batch_id = new_source_batch_id()
        if not fetch_result.has_publishable_rows:
            error_summary = self._error_summary(fetch_result)
            record_unpublishable_snapshot(
                fetch_result=fetch_result,
                snapshot_time=snapshot_time,
                source_batch_id=source_batch_id,
            )
            mark_failed(self.module_id, self.dataset_key, snapshot_time.date(), error_summary)
            raise UnpublishableEastmoneySnapshot(error_summary)

        missing_direction_count = self._missing_direction_count(fetch_result)
        publication = begin_publication(
            self.module_id,
            self.dataset_key,
            snapshot_time.date(),
            len(fetch_result.rows) + missing_direction_count,
        )
        try:
            write_result = write_publishable_snapshot(
                fetch_result=fetch_result,
                snapshot_time=snapshot_time,
                source_batch_id=source_batch_id,
            )
            finish_publication(publication, write_result.record_count, missing_direction_count)
        except Exception as error:
            fail_publication(publication, error)
            raise

        cache = default_file_cache()
        if cache is not None:
            cache.invalidate_module(self.module_id)
        return {
            'record_count': write_result.record_count,
            'partial': missing_direction_count > 0,
            'dry_run': False,
        }

    def format_success_message(self, result, options) -> str:
        mode = 'would publish' if result['dry_run'] else 'published'
        completeness = 'partial ' if result['partial'] else ''
        return f"{mode} {completeness}{result['record_count']} Eastmoney sector fund-flow records."

    @staticmethod
    def _is_trading_session(now) -> bool:
        if now.weekday() >= 5 or not TradingDay.objects.filter(trade_date=now.date()).exists():
            return False
        current_time = now.time()
        return time(9, 30) <= current_time <= time(11, 30) or time(13, 0) <= current_time <= time(15, 0)

    @staticmethod
    def _snapshot_time(now):
        return now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)

    @staticmethod
    def _missing_direction_count(fetch_result) -> int:
        return int(not fetch_result.inflow.succeeded) + int(not fetch_result.outflow.succeeded)

    @staticmethod
    def _error_summary(fetch_result) -> str:
        errors = [
            result.error_summary
            for result in (fetch_result.inflow, fetch_result.outflow)
            if result.error_summary
        ]
        return '; '.join(dict.fromkeys(errors)) or 'Eastmoney returned no publishable sector rows.'
