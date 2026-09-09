"""Transactional persistence for complete Kaipanla fund-flow snapshots."""

from dataclasses import dataclass
from uuid import uuid4

from django.db import transaction
from django.utils import timezone

from kaipanla.models import KaipanlaSectorFundFlowRun, KaipanlaSectorFundFlowSnapshot
from kaipanla.services.fetcher import KaipanlaSectorFundFlowFetchResult


class IncompleteKaipanlaSnapshot(ValueError):
    """Raised when a paginated upstream result cannot safely be published."""


@dataclass(frozen=True)
class KaipanlaSnapshotWriteResult:
    source_batch_id: str
    record_count: int


def new_source_batch_id() -> str:
    return uuid4().hex


def write_complete_snapshot(
    *,
    fetch_result: KaipanlaSectorFundFlowFetchResult,
    snapshot_time,
    source_batch_id: str,
) -> KaipanlaSnapshotWriteResult:
    """Upsert a fully fetched five-minute snapshot in the Kaipanla database."""
    if not fetch_result.is_complete or not fetch_result.rows:
        raise IncompleteKaipanlaSnapshot(
            fetch_result.error_summary or 'Kaipanla snapshot collection was incomplete.'
        )

    snapshots = [
        KaipanlaSectorFundFlowSnapshot(
            sector_code=row.sector_code,
            sector_name=row.sector_name,
            trade_date=snapshot_time.date(),
            snapshot_time=snapshot_time,
            change_pct=row.change_pct,
            main_net_inflow=row.main_net_inflow,
            main_buy=row.main_buy,
            main_sell=row.main_sell,
            large_order_net_inflow=row.large_order_net_inflow,
            volume_ratio=row.volume_ratio,
            turnover_amount=row.turnover_amount,
            float_market_cap=row.float_market_cap,
            total_market_cap=row.total_market_cap,
            source_batch_id=source_batch_id,
        )
        for row in fetch_result.rows
    ]
    now = timezone.now()
    try:
        with transaction.atomic(using='kaipanla'):
            KaipanlaSectorFundFlowRun.objects.using('kaipanla').create(
                source_batch_id=source_batch_id,
                trade_date=snapshot_time.date(),
                snapshot_time=snapshot_time,
                status=KaipanlaSectorFundFlowRun.Status.RUNNING,
                expected_page_count=fetch_result.expected_page_count,
                completed_page_count=fetch_result.completed_page_count,
                failed_page_offsets=list(fetch_result.failed_page_offsets),
                expected_record_count=len(snapshots),
                started_at=now,
            )
            KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').bulk_create(
                snapshots,
                update_conflicts=True,
                update_fields=[
                    'sector_name',
                    'trade_date',
                    'change_pct',
                    'main_net_inflow',
                    'main_buy',
                    'main_sell',
                    'large_order_net_inflow',
                    'volume_ratio',
                    'turnover_amount',
                    'float_market_cap',
                    'total_market_cap',
                    'source_batch_id',
                ],
                unique_fields=['sector_code', 'snapshot_time'],
                batch_size=500,
            )
            KaipanlaSectorFundFlowRun.objects.using('kaipanla').filter(
                source_batch_id=source_batch_id
            ).update(
                status=KaipanlaSectorFundFlowRun.Status.COMPLETE,
                actual_record_count=len(snapshots),
                missing_record_count=0,
                finished_at=timezone.now(),
            )
    except Exception as error:
        _record_failed_run(fetch_result, snapshot_time, source_batch_id, str(error))
        raise

    return KaipanlaSnapshotWriteResult(source_batch_id, len(snapshots))


def record_incomplete_snapshot(
    *,
    fetch_result: KaipanlaSectorFundFlowFetchResult,
    snapshot_time,
    source_batch_id: str,
) -> None:
    """Record a failed collection without changing any existing snapshots."""
    _record_failed_run(
        fetch_result,
        snapshot_time,
        source_batch_id,
        fetch_result.error_summary or 'Kaipanla snapshot collection was incomplete.',
    )


def _record_failed_run(fetch_result, snapshot_time, source_batch_id: str, error_summary: str) -> None:
    KaipanlaSectorFundFlowRun.objects.using('kaipanla').update_or_create(
        source_batch_id=source_batch_id,
        defaults={
            'trade_date': snapshot_time.date(),
            'snapshot_time': snapshot_time,
            'status': KaipanlaSectorFundFlowRun.Status.FAILED,
            'expected_page_count': fetch_result.expected_page_count,
            'completed_page_count': fetch_result.completed_page_count,
            'failed_page_offsets': list(fetch_result.failed_page_offsets),
            'expected_record_count': len(fetch_result.rows),
            'actual_record_count': 0,
            'missing_record_count': len(fetch_result.rows),
            'finished_at': timezone.now(),
            'error_summary': error_summary[:1000],
        },
    )
