"""Persistence helpers for the lightweight admin-visible run status."""

from datetime import date

from django.utils import timezone

from core.models import DataVersion, ModuleRunStatus


def mark_running(module_id: str, dataset_key: str, business_date: date | None) -> ModuleRunStatus:
    status, _ = ModuleRunStatus.objects.update_or_create(
        module_id=module_id,
        dataset_key=dataset_key,
        defaults={
            'status': ModuleRunStatus.Status.RUNNING,
            'completeness': DataVersion.Status.RUNNING,
            'business_date': business_date,
            'serving_stale': False,
            'error_summary': '',
        },
    )
    return status


def mark_finished(
    module_id: str,
    dataset_key: str,
    business_date: date | None,
    version: str,
    completeness: str,
) -> ModuleRunStatus:
    """Record one run's outcome on the single, in-place status row of a dataset.

    ``last_success_at`` only moves forward on a **complete** run; a partial run
    keeps whatever was already recorded. This row is the only place that can
    answer "when did this dataset last produce a complete result?", so a partial
    run must not blank it. ``DataVersion.last_success_at`` can afford to be NULL
    on a partial version precisely because every run gets its own row there (and
    the read paths sort by it) — the two fields are per-version vs per-dataset,
    not two spellings of the same thing.
    """
    is_complete = completeness == DataVersion.Status.COMPLETE
    previous = ModuleRunStatus.objects.filter(
        module_id=module_id, dataset_key=dataset_key
    ).first()
    status, _ = ModuleRunStatus.objects.update_or_create(
        module_id=module_id,
        dataset_key=dataset_key,
        defaults={
            'status': ModuleRunStatus.Status.SUCCESS,
            'completeness': completeness,
            'business_date': business_date,
            'last_success_at': (
                timezone.now()
                if is_complete
                else (previous.last_success_at if previous else None)
            ),
            'source_data_version': version,
            'serving_stale': not is_complete,
            'consecutive_failure_count': 0,
            'error_summary': '',
        },
    )
    return status


def mark_failed(
    module_id: str, dataset_key: str, business_date: date | None, error_summary: str
) -> ModuleRunStatus:
    previous = ModuleRunStatus.objects.filter(
        module_id=module_id, dataset_key=dataset_key
    ).first()
    status, _ = ModuleRunStatus.objects.update_or_create(
        module_id=module_id,
        dataset_key=dataset_key,
        defaults={
            'status': ModuleRunStatus.Status.FAILED,
            'completeness': DataVersion.Status.FAILED,
            'business_date': business_date,
            'source_data_version': previous.source_data_version if previous else '',
            'serving_stale': True,
            'consecutive_failure_count': (
                (previous.consecutive_failure_count if previous else 0) + 1
            ),
            'error_summary': error_summary[:1000],
        },
    )
    return status
