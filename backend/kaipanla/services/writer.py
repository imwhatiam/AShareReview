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


def record_counts(fetch_result: KaipanlaSectorFundFlowFetchResult) -> tuple[int, int, int]:
    """Return ``(expected, collected, missing)`` rows for one collection.

    ``expected`` is what the upstream said it had (``Count``), ``collected`` is
    what we actually got. The difference covers both rows we could not parse and
    rows the upstream counted but never delivered.

    This used to be ``expected_record_count=len(snapshots)``: passing the actual
    count as the expected one made the completeness check prove itself, and
    ``missing_record_count`` was hard-coded to 0 on every path — the two fields an
    operator would look at first carried no information at all.

    Note this is the **row-level** account kept on ``KaipanlaSectorFundFlowRun``.
    ``DataVersion`` keeps the **page-level** one (we wrote as many rows as we set
    out to write, so ``missing=0`` and the snapshot can be published); mixing the
    two would turn a single unparsable upstream row into an unpublished snapshot.
    """
    collected = len(fetch_result.rows)
    expected = fetch_result.upstream_record_count
    if expected is None or expected < collected:
        expected = collected
    return expected, collected, expected - collected


def write_complete_snapshot(
    *,
    fetch_result: KaipanlaSectorFundFlowFetchResult,
    snapshot_time,
    source_batch_id: str,
    source_data_version: str,
) -> KaipanlaSnapshotWriteResult:
    """Upsert a fully fetched five-minute snapshot in the Kaipanla database.

    ``source_data_version`` is stamped on every row: the rows and the
    ``DataVersion`` that publishes them are committed by two different databases,
    so a crash in between used to leave rows that are readable but unpublished —
    and the read path, serving the newest *complete* version, handed them out
    under that older version's name. Rows now carry the version that produced
    them, and the read path only serves rows from complete publications.
    """
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
            source_data_version=source_data_version,
            source_batch_id=source_batch_id,
        )
        for row in fetch_result.rows
    ]
    expected_record_count, actual_record_count, missing_record_count = record_counts(fetch_result)
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
                expected_record_count=expected_record_count,
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
                    'source_data_version',
                    'source_batch_id',
                ],
                unique_fields=['sector_code', 'snapshot_time'],
                batch_size=500,
            )
            KaipanlaSectorFundFlowRun.objects.using('kaipanla').filter(
                source_batch_id=source_batch_id
            ).update(
                status=KaipanlaSectorFundFlowRun.Status.COMPLETE,
                actual_record_count=actual_record_count,
                missing_record_count=missing_record_count,
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
    expected_record_count, collected_record_count, missing_record_count = record_counts(fetch_result)
    KaipanlaSectorFundFlowRun.objects.using('kaipanla').update_or_create(
        source_batch_id=source_batch_id,
        defaults={
            'trade_date': snapshot_time.date(),
            'snapshot_time': snapshot_time,
            'status': KaipanlaSectorFundFlowRun.Status.FAILED,
            'expected_page_count': fetch_result.expected_page_count,
            'completed_page_count': fetch_result.completed_page_count,
            'failed_page_offsets': list(fetch_result.failed_page_offsets),
            'expected_record_count': expected_record_count,
            # 采集到多少行就记多少行（可能是"页失败，只收到一半"），缺多少行由
            # 上游 Count 与实际之差给出。旧代码写的是 actual=0 / missing=收到行数，
            # 两个字段互相矛盾且毫无用处。
            'actual_record_count': collected_record_count,
            'missing_record_count': missing_record_count,
            'finished_at': timezone.now(),
            'error_summary': error_summary[:1000],
        },
    )
