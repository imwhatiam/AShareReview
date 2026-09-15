"""Fetch and store one complete Kaipanla sector fund-flow snapshot."""

import logging
from zoneinfo import ZoneInfo

from django.utils import timezone

from core.logging import log_command_progress, log_event
from core.management.base import BaseDataCommand
from core.services.calendar import is_trading_session
from core.services.file_cache import default_file_cache
from kaipanla.services.fetcher import KaipanlaSectorFundFlowFetcher
from kaipanla.services.intraday import resolve_snapshot_slot
from kaipanla.services.writer import IncompleteKaipanlaSnapshot, write_complete_snapshot

SHANGHAI_TIME_ZONE = ZoneInfo('Asia/Shanghai')

logger = logging.getLogger(__name__)


def _log_incomplete_collection(fetch_result, snapshot_time) -> None:
    """Write the failure account that used to be a ``KaipanlaSectorFundFlowRun`` row.

    That table answered exactly three questions — how many rows the upstream
    claimed, how many actually arrived, and which page failed — so those three
    are what this line carries. They belong in the command log: a collection that
    does not publish leaves no trace in the database at all, which is the point
    of dropping the run table.
    """
    expected = fetch_result.upstream_record_count
    collected = len(fetch_result.rows)
    log_event(
        logger,
        'kaipanla_collection_incomplete',
        level=logging.WARNING,
        snapshot_time=snapshot_time,
        expected_record_count=expected,
        collected_record_count=collected,
        missing_record_count=(
            expected - collected if expected is not None and expected > collected else 0
        ),
        invalid_record_count=fetch_result.invalid_row_count,
        page_progress=f'{fetch_result.completed_page_count}/{fetch_result.expected_page_count}',
        failed_page_offsets=list(fetch_result.failed_page_offsets),
        failure_kind=fetch_result.failure_kind,
        detail=fetch_result.error_summary,
    )


class Command(BaseDataCommand):
    help = 'Fetch and store a complete Kaipanla sector fund-flow snapshot.'
    module_id = 'kaipanla'
    dataset_key = 'kaipanla_sector_fund_flow'
    failure_message = 'Kaipanla sector fund-flow synchronization failed.'

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            '--latest',
            action='store_true',
            help='Run even outside the trading sessions (midday break, after the close, non-trading day).',
        )

    def run_data_sync(self, options):
        now = timezone.localtime(timezone.now(), SHANGHAI_TIME_ZONE)
        # 默认模式是"盘中采集"的闸门：交易时段外上游只有已收盘的静态数据，跑一次
        # 既拿不到新东西，又白打上游。这里直接跳过并返回结果（退出码 0、不写失败
        # 日志），让 crontab 拿到一次干净的"什么都没发生"—— 这正是调度器期望的语义。
        # 需要强制采集（补数、盘后修复）时用 --latest。
        if not options['latest'] and not is_trading_session(now):
            log_command_progress(
                'kaipanla_sector_fund_flow',
                action='skipped',
                reason='outside_trading_session',
            )
            return {'skipped': True, 'record_count': 0, 'dry_run': options['dry_run']}

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

        if not fetch_result.is_complete or not fetch_result.rows:
            # 采集不全就一个字都不写：缺页的部分快照会让一批板块从曲线上整批消失，
            # 而库里没有任何东西能说明它缺了。失败只留日志（含上游行数与页进度），
            # 由 BaseDataCommand 收尾成一条 `data_command_failed` 并以非零退出码结束。
            _log_incomplete_collection(fetch_result, snapshot_time)
            raise IncompleteKaipanlaSnapshot(
                fetch_result.error_summary or 'Kaipanla snapshot collection was incomplete.'
            )

        if options['dry_run']:
            return {'record_count': len(fetch_result.rows), 'dry_run': True}

        log_command_progress(
            'kaipanla_sector_fund_flow',
            action='writing',
            snapshot_time=snapshot_time,
            records=len(fetch_result.rows),
        )
        # 写行即发布：整个槽位一次 `INSERT ... ON CONFLICT DO UPDATE`、一个事务。
        record_count = write_complete_snapshot(
            fetch_result=fetch_result,
            snapshot_time=snapshot_time,
        )

        cache = default_file_cache()
        if cache is not None:
            cache.invalidate_module(self.module_id)
        return {'record_count': record_count, 'dry_run': False}

    def format_success_message(self, result, options) -> str:
        if result.get('skipped'):
            return 'skipped: outside the A-share trading sessions (pass --latest to force a run).'
        if result['dry_run']:
            return f"dry-run: would publish {result['record_count']} Kaipanla sector fund-flow records."
        return f"published {result['record_count']} Kaipanla sector fund-flow records."
