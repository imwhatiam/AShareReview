"""Transactional lifecycle for publishing versioned public datasets."""

from dataclasses import dataclass
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
