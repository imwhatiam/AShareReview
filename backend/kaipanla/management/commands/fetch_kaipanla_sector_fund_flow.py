"""Fetch and publish one complete Kaipanla sector fund-flow snapshot."""

from datetime import datetime, time
from zoneinfo import ZoneInfo

from django.core.management.base import CommandError
from django.utils import timezone

from core.management.base import BaseDataCommand
from core.models import TradingDay
from core.services.file_cache import default_file_cache
from core.services.publication import begin_publication, fail_publication, finish_publication
from core.services.run_status import mark_failed
from kaipanla.services.fetcher import KaipanlaSectorFundFlowFetcher
from kaipanla.services.writer import (
    IncompleteKaipanlaSnapshot,
    new_source_batch_id,
    record_incomplete_snapshot,
    write_complete_snapshot,
)

SHANGHAI_TIME_ZONE = ZoneInfo('Asia/Shanghai')


class Command(BaseDataCommand):
    help = 'Fetch and publish a complete Kaipanla sector fund-flow snapshot.'
    module_id = 'kaipanla'
    dataset_key = 'kaipanla_sector_fund_flow'
    failure_message = 'Kaipanla sector fund-flow synchronization failed.'

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            '--latest',
            action='store_true',
            help='Fetch the latest upstream snapshot outside normal trading hours.',
        )

    def run_data_sync(self, options):
        now = timezone.localtime(timezone.now(), SHANGHAI_TIME_ZONE)
        if not options['latest'] and not self._is_trading_session(now):
            raise ValueError('The default mode is only available during an A-share trading session.')

        fetch_result = KaipanlaSectorFundFlowFetcher().fetch()
        snapshot_time = self._snapshot_time(fetch_result, now, latest=options['latest'])
        if options['dry_run']:
            if not fetch_result.is_complete or not fetch_result.rows:
                raise IncompleteKaipanlaSnapshot(
                    fetch_result.error_summary or 'Kaipanla snapshot collection was incomplete.'
                )
            return {'record_count': len(fetch_result.rows), 'dry_run': True}

        source_batch_id = new_source_batch_id()
        if not fetch_result.is_complete or not fetch_result.rows:
            record_incomplete_snapshot(
                fetch_result=fetch_result,
                snapshot_time=snapshot_time,
                source_batch_id=source_batch_id,
            )
            mark_failed(
                self.module_id,
                self.dataset_key,
                snapshot_time.date(),
                fetch_result.error_summary or 'Kaipanla snapshot collection was incomplete.',
            )
            raise IncompleteKaipanlaSnapshot(
                fetch_result.error_summary or 'Kaipanla snapshot collection was incomplete.'
            )

        publication = begin_publication(
            self.module_id,
            self.dataset_key,
            snapshot_time.date(),
            len(fetch_result.rows),
        )
        try:
            write_result = write_complete_snapshot(
                fetch_result=fetch_result,
                snapshot_time=snapshot_time,
                source_batch_id=source_batch_id,
            )
            finish_publication(publication, write_result.record_count, 0)
        except Exception as error:
            fail_publication(publication, error)
            raise

        cache = default_file_cache()
        if cache is not None:
            cache.invalidate_module(self.module_id)
        return {'record_count': write_result.record_count, 'dry_run': False}

    def format_success_message(self, result, options) -> str:
        if result['dry_run']:
            return f"dry-run: would publish {result['record_count']} Kaipanla sector fund-flow records."
        return f"published {result['record_count']} Kaipanla sector fund-flow records."

    @staticmethod
    def _is_trading_session(now) -> bool:
        if now.weekday() >= 5:
            return False
        if not TradingDay.objects.filter(trade_date=now.date()).exists():
            return False
        current_time = now.time()
        return time(9, 30) <= current_time <= time(11, 30) or time(13, 0) <= current_time <= time(15, 0)

    @staticmethod
    def _snapshot_time(fetch_result, now, *, latest: bool):
        if not latest:
            return now.replace(minute=(now.minute // 5) * 5, second=0, microsecond=0)
        try:
            raw_timestamp = int(fetch_result.source_timestamp)
        except (TypeError, ValueError) as error:
            raise ValueError('Kaipanla latest mode requires an upstream snapshot timestamp.') from error
        if raw_timestamp > 10**11:
            raw_timestamp //= 1000
        source_time = datetime.fromtimestamp(raw_timestamp, SHANGHAI_TIME_ZONE)
        return source_time.replace(minute=(source_time.minute // 5) * 5, second=0, microsecond=0)
