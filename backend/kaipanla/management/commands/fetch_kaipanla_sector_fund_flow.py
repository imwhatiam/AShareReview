"""Fetch and publish one complete Kaipanla sector fund-flow snapshot."""

from datetime import time
from zoneinfo import ZoneInfo

from django.utils import timezone

from core.management.base import BaseDataCommand
from core.logging import log_command_progress
from core.models import TradingDay
from core.services.file_cache import default_file_cache
from core.services.publication import begin_publication, publish_with_writer
from core.services.run_status import mark_failed
from kaipanla.services.fetcher import KaipanlaSectorFundFlowFetcher
from kaipanla.services.intraday import resolve_snapshot_slot
from kaipanla.services.writer import (
    IncompleteKaipanlaSnapshot,
    KaipanlaSnapshotWriteResult,
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
            help='Allow a run outside the trading sessions (midday break, after the close, non-trading day).',
        )

    def run_data_sync(self, options):
        now = timezone.localtime(timezone.now(), SHANGHAI_TIME_ZONE)
        if not options['latest'] and not self._is_trading_session(now):
            raise ValueError('The default mode is only available during an A-share trading session.')

        log_command_progress('kaipanla_sector_fund_flow', action='fetching')
        fetch_result = KaipanlaSectorFundFlowFetcher().fetch()
        log_command_progress(
            'kaipanla_sector_fund_flow',
            action='fetched',
            is_complete=fetch_result.is_complete,
            records=len(fetch_result.rows),
            pages=f'{fetch_result.completed_page_count}/{fetch_result.expected_page_count}',
        )
        # 快照归属由运行时刻决定：盘中回退到所在 5 分钟槽，午休回退到 11:30，
        # 收盘后落在 15:00，非交易日/开盘前落在最近一个交易日的 15:00。
        snapshot_time = resolve_snapshot_slot(now)
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
        log_command_progress(
            'kaipanla_sector_fund_flow',
            action='writing',
            snapshot_time=snapshot_time,
            records=len(fetch_result.rows),
        )
        # 写行与发布版本交给 publish_with_writer：失败路径只有一处（写失败 ⇒ 版本
        # 标 failed），而且行上会盖上本批次的版本号，读路径只认已发布版本的行 ——
        # 于是"行已落库但版本还没标 complete"这个崩溃窗口里的数据永远不会被返回。
        write_result: KaipanlaSnapshotWriteResult | None = None

        def write_rows() -> None:
            nonlocal write_result
            write_result = write_complete_snapshot(
                fetch_result=fetch_result,
                snapshot_time=snapshot_time,
                source_batch_id=source_batch_id,
                source_data_version=publication.version,
            )

        publish_with_writer(
            publication,
            write_rows,
            actual_record_count=len(fetch_result.rows),
            missing_record_count=0,
        )

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
