"""Synchronize the public Kaipanla industry-to-stock snapshot."""

from dataclasses import dataclass, replace
from datetime import date
from typing import Any

from django.db import transaction
from django.utils import timezone

from core.integrations.kaipanla.client import KaipanlaIndustryClient
from core.models import DataVersion, IndustrySnapshot
from core.services.publication import (
    PublicationRun,
    begin_publication,
    fail_publication,
    publish_with_writer,
)

_DATASET_KEY = 'industry_snapshot'


@dataclass(frozen=True)
class IndustrySnapshotSyncResult:
    dataset_key: str
    record_count: int
    dry_run: bool


def _normalize_industry(record: Any, label: str) -> tuple[str, str]:
    if not isinstance(record, dict):
        raise ValueError(f'Kaipanla {label} industry record must be an object.')
    code = str(record.get('industry_code', '')).strip()
    name = str(record.get('industry_name', '')).strip()
    if not code or not name:
        raise ValueError(f'Kaipanla {label} industry record is missing a code or name.')
    return code, name


def _normalize_stock_codes(stock_codes: Any, industry_code: str) -> list[str]:
    if not isinstance(stock_codes, (tuple, list)):
        raise ValueError(f'Kaipanla stock list for {industry_code} is invalid.')
    normalized = sorted({str(stock_code).strip() for stock_code in stock_codes if str(stock_code).strip()})
    if not normalized:
        raise ValueError(f'Kaipanla stock list for {industry_code} is empty.')
    return normalized


def _collect_industry_snapshot(client: KaipanlaIndustryClient) -> tuple[dict[str, Any], ...]:
    parents = tuple(client.list_parent_industries())
    if not parents:
        raise ValueError('Kaipanla returned an empty parent industry list.')

    records: list[dict[str, Any]] = []
    seen_parent_codes: set[str] = set()
    seen_industry_codes: set[str] = set()
    for parent in parents:
        parent_code, parent_name = _normalize_industry(parent, 'parent')
        if parent_code in seen_parent_codes:
            raise ValueError(f'Kaipanla returned duplicate parent industry {parent_code}.')
        seen_parent_codes.add(parent_code)
        seen_industry_codes.add(parent_code)

        children = tuple(client.list_child_industries(parent_code))
        parent_stock_codes: set[str] = set()
        for child in children:
            child_code, child_name = _normalize_industry(child, 'child')
            if child_code in seen_industry_codes:
                raise ValueError(f'Kaipanla returned duplicate industry {child_code}.')
            child_stock_codes = _normalize_stock_codes(
                client.list_stock_codes(child_code), child_code
            )
            seen_industry_codes.add(child_code)
            parent_stock_codes.update(child_stock_codes)
            records.append({
                'industry_code': child_code,
                'industry_name': child_name,
                'industry_level': IndustrySnapshot.Level.CHILD,
                'stock_codes': child_stock_codes,
            })

        if not children:
            parent_stock_codes.update(
                _normalize_stock_codes(client.list_stock_codes(parent_code), parent_code)
            )

        records.append({
            'industry_code': parent_code,
            'industry_name': parent_name,
            'industry_level': IndustrySnapshot.Level.PARENT,
            'stock_codes': sorted(parent_stock_codes),
        })

    return tuple(records)


def _set_publication_details(run: PublicationRun, record_count: int) -> PublicationRun:
    business_date = timezone.localdate()
    DataVersion.objects.filter(version=run.version).update(
        expected_record_count=record_count,
        business_date=business_date,
    )
    return replace(
        run,
        expected_record_count=record_count,
        business_date=business_date,
    )


def sync_kaipanla_industry_snapshot(*, dry_run: bool = False) -> IndustrySnapshotSyncResult:
    client = KaipanlaIndustryClient()
    if dry_run:
        records = _collect_industry_snapshot(client)
        return IndustrySnapshotSyncResult(_DATASET_KEY, len(records), True)

    run = begin_publication('core', _DATASET_KEY, None, 0)
    try:
        records = _collect_industry_snapshot(client)
        run = _set_publication_details(run, len(records))
    except Exception as error:
        fail_publication(run, error)
        raise

    def write_records():
        IndustrySnapshot.objects.all().delete()
        IndustrySnapshot.objects.bulk_create(
            [IndustrySnapshot(**record) for record in records]
        )

    publish_with_writer(
        run,
        write_records,
        actual_record_count=len(records),
        missing_record_count=0,
    )
    return IndustrySnapshotSyncResult(_DATASET_KEY, len(records), False)
