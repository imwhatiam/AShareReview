"""Transactional persistence for Eastmoney complete or partial snapshots."""

from dataclasses import dataclass
from uuid import uuid4

from django.db import transaction
from django.utils import timezone

from eastmoney.models import EastmoneySectorFundFlowRun, EastmoneySectorFundFlowSnapshot
from eastmoney.services.fetcher import EastmoneySectorFundFlowFetchResult


class UnpublishableEastmoneySnapshot(ValueError):
    """Raised when neither ranking supplied usable snapshot rows."""


@dataclass(frozen=True)
class EastmoneySnapshotWriteResult:
    source_batch_id: str
    record_count: int
    status: str


def new_source_batch_id() -> str:
    return uuid4().hex


def write_publishable_snapshot(
    *,
    fetch_result: EastmoneySectorFundFlowFetchResult,
    snapshot_time,
    source_batch_id: str,
) -> EastmoneySnapshotWriteResult:
    """Upsert all usable rows and record complete or partial direction status."""
    if not fetch_result.has_publishable_rows:
        raise UnpublishableEastmoneySnapshot(_result_error_summary(fetch_result))

    status = _publication_status(fetch_result)
    snapshots = [
        EastmoneySectorFundFlowSnapshot(
            **row,
            trade_date=snapshot_time.date(),
            snapshot_time=snapshot_time,
            source_batch_id=source_batch_id,
        )
        for row in fetch_result.rows
    ]
    try:
        with transaction.atomic(using='eastmoney'):
            EastmoneySectorFundFlowRun.objects.using('eastmoney').create(
                source_batch_id=source_batch_id,
                trade_date=snapshot_time.date(),
                snapshot_time=snapshot_time,
                status=EastmoneySectorFundFlowRun.Status.RUNNING,
            )
            EastmoneySectorFundFlowSnapshot.objects.using('eastmoney').bulk_create(
                snapshots,
                update_conflicts=True,
                update_fields=[
                    'sector_name',
                    'trade_date',
                    'latest_index',
                    'change_pct',
                    'main_net_inflow',
                    'main_net_inflow_ratio',
                    'super_large_net_inflow',
                    'large_net_inflow',
                    'medium_net_inflow',
                    'small_net_inflow',
                    'source_batch_id',
                ],
                unique_fields=['sector_code', 'snapshot_time'],
                batch_size=500,
            )
            EastmoneySectorFundFlowRun.objects.using('eastmoney').filter(
                source_batch_id=source_batch_id
            ).update(
                status=status,
                inflow_status=_direction_status(fetch_result.inflow.succeeded),
                outflow_status=_direction_status(fetch_result.outflow.succeeded),
                inflow_record_count=fetch_result.inflow.record_count,
                outflow_record_count=fetch_result.outflow.record_count,
                inflow_error_summary=fetch_result.inflow.error_summary,
                outflow_error_summary=fetch_result.outflow.error_summary,
                finished_at=timezone.now(),
                error_summary=_result_error_summary(fetch_result),
            )
    except Exception as error:
        _record_failed_run(fetch_result, snapshot_time, source_batch_id, str(error))
        raise

    return EastmoneySnapshotWriteResult(source_batch_id, len(snapshots), status)


def record_unpublishable_snapshot(
    *,
    fetch_result: EastmoneySectorFundFlowFetchResult,
    snapshot_time,
    source_batch_id: str,
) -> None:
    """Record a blocked or failed upstream collection without touching snapshots."""
    _record_failed_run(
        fetch_result,
        snapshot_time,
        source_batch_id,
        _result_error_summary(fetch_result),
    )


def _record_failed_run(fetch_result, snapshot_time, source_batch_id: str, error_summary: str) -> None:
    EastmoneySectorFundFlowRun.objects.using('eastmoney').update_or_create(
        source_batch_id=source_batch_id,
        defaults={
            'trade_date': snapshot_time.date(),
            'snapshot_time': snapshot_time,
            'status': EastmoneySectorFundFlowRun.Status.FAILED,
            'inflow_status': EastmoneySectorFundFlowRun.DirectionStatus.FAILED,
            'outflow_status': EastmoneySectorFundFlowRun.DirectionStatus.FAILED,
            'inflow_record_count': fetch_result.inflow.record_count,
            'outflow_record_count': fetch_result.outflow.record_count,
            'inflow_error_summary': fetch_result.inflow.error_summary,
            'outflow_error_summary': fetch_result.outflow.error_summary,
            'finished_at': timezone.now(),
            'error_summary': error_summary[:1000],
        },
    )


def _publication_status(fetch_result: EastmoneySectorFundFlowFetchResult) -> str:
    if fetch_result.inflow.succeeded and fetch_result.outflow.succeeded:
        return EastmoneySectorFundFlowRun.Status.COMPLETE
    return EastmoneySectorFundFlowRun.Status.PARTIAL


def _direction_status(succeeded: bool) -> str:
    return (
        EastmoneySectorFundFlowRun.DirectionStatus.COMPLETE
        if succeeded
        else EastmoneySectorFundFlowRun.DirectionStatus.FAILED
    )


def _result_error_summary(fetch_result: EastmoneySectorFundFlowFetchResult) -> str:
    errors = [
        result.error_summary
        for result in (fetch_result.inflow, fetch_result.outflow)
        if result.error_summary
    ]
    return '; '.join(dict.fromkeys(errors)) or 'Eastmoney returned no publishable sector rows.'
