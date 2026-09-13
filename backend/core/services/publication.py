"""Transactional lifecycle for publishing versioned public datasets."""

from dataclasses import dataclass, replace
from datetime import date
from typing import Callable
from uuid import uuid4

from django.db import transaction
from django.utils import timezone

from core.models import DataVersion
from core.services.run_status import mark_failed, mark_finished, mark_running


@dataclass(frozen=True)
class PublicationRun:
    module_id: str
    dataset_key: str
    business_date: date | None
    expected_record_count: int
    version: str


def begin_publication(
    module_id: str,
    dataset_key: str,
    business_date: date | None,
    expected_record_count: int,
) -> PublicationRun:
    if expected_record_count < 0:
        raise ValueError('expected_record_count must be non-negative.')
    version = f'{dataset_key}-{uuid4().hex}'
    DataVersion.objects.create(
        dataset_key=dataset_key,
        version=version,
        business_date=business_date,
        status=DataVersion.Status.RUNNING,
        expected_record_count=expected_record_count,
    )
    mark_running(module_id, dataset_key, business_date)
    return PublicationRun(
        module_id=module_id,
        dataset_key=dataset_key,
        business_date=business_date,
        expected_record_count=expected_record_count,
        version=version,
    )


def set_publication_details(
    run: PublicationRun, record_count: int, business_date: date | None
) -> PublicationRun:
    """Fill in the record count and business date a fetch only reveals afterwards.

    ``begin_publication`` must run *before* the upstream fetch — that way a crash
    mid-fetch still leaves a RUNNING version (and a running status row) behind
    instead of nothing. But neither number is known at that point, so two callers
    (stock master / trading calendar, and the industry snapshot) used to carry
    byte-identical private copies of this rewrite. It lives here now:
    ``finish_publication`` compares ``actual_record_count`` against
    ``expected_record_count``, so a stale count silently turns every run into
    PARTIAL.

    The returned run must be the one passed to ``publish_with_writer`` /
    ``finish_publication`` — those read the counts off the dataclass, not the row.
    """
    DataVersion.objects.filter(version=run.version).update(
        expected_record_count=record_count,
        business_date=business_date,
    )
    return replace(
        run,
        expected_record_count=record_count,
        business_date=business_date,
    )


def supersede_previous_versions(
    dataset_key: str, business_date: date, *, keep_version: str
) -> int:
    """Stop the versions a rerun replaced from claiming rows they no longer hold.

    Re-running a publication for a business day that already had a COMPLETE
    version creates a second one and re-stamps every row of that day to the new
    version — the read path filters rows by ``source_data_version``, so those rows
    genuinely belong to the new version now. The old ``DataVersion`` row keeps
    ``status=complete``: that a run completed is history and must not be
    rewritten. Its ``expected``/``actual`` counts, however, are not history —
    they are the version's *current* footprint — and leaving them alone made the
    admin list show two "complete" versions with full counts for the same day, so
    an operator could not tell which one the store was serving.

    Resetting the three counts to zero restores the invariant an operator reads
    the list with: exactly one COMPLETE row per business day has a non-zero count,
    and it is the live one. Returns the number of versions retired.

    Only COMPLETE and PARTIAL rows are touched — RUNNING/FAILED versions never
    claimed a published footprint.
    """
    return (
        DataVersion.objects.filter(
            dataset_key=dataset_key,
            business_date=business_date,
            status__in=(DataVersion.Status.COMPLETE, DataVersion.Status.PARTIAL),
        )
        .exclude(version=keep_version)
        .update(
            expected_record_count=0,
            actual_record_count=0,
            missing_record_count=0,
        )
    )


def finish_publication(
    run: PublicationRun, actual_record_count: int, missing_record_count: int
) -> DataVersion:
    if actual_record_count < 0 or missing_record_count < 0:
        raise ValueError('Record counts must be non-negative.')
    is_complete = (
        actual_record_count == run.expected_record_count and missing_record_count == 0
    )
    status = DataVersion.Status.COMPLETE if is_complete else DataVersion.Status.PARTIAL
    with transaction.atomic():
        version = DataVersion.objects.select_for_update().get(version=run.version)
        version.status = status
        version.actual_record_count = actual_record_count
        version.missing_record_count = missing_record_count
        version.finished_at = timezone.now()
        version.last_success_at = timezone.now() if is_complete else None
        version.save(
            update_fields=[
                'status',
                'actual_record_count',
                'missing_record_count',
                'finished_at',
                'last_success_at',
            ]
        )
        mark_finished(
            run.module_id,
            run.dataset_key,
            run.business_date,
            run.version,
            status,
        )
    return version


def fail_publication(run: PublicationRun, error: Exception) -> None:
    DataVersion.objects.filter(version=run.version).update(
        status=DataVersion.Status.FAILED,
        finished_at=timezone.now(),
        error_summary=str(error)[:1000],
    )
    mark_failed(run.module_id, run.dataset_key, run.business_date, str(error))


def publish_with_writer(
    run: PublicationRun,
    write_records: Callable[[], None],
    actual_record_count: int,
    missing_record_count: int,
) -> DataVersion:
    try:
        with transaction.atomic():
            write_records()
            return finish_publication(run, actual_record_count, missing_record_count)
    except Exception as error:
        fail_publication(run, error)
        raise
