from datetime import date, datetime
from typing import Any

from django.http import JsonResponse
from django.utils import timezone


def _iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def api_response(
    *,
    status: str,
    http_status: int,
    data: Any = None,
    business_date: date | None = None,
    data_version: str | None = None,
    stale: bool = False,
    source: str | None = None,
    preparation_state: str = 'ready',
    retry_after_seconds: int | None = None,
    warnings: list[str] | None = None,
    error: dict[str, str] | None = None,
) -> JsonResponse:
    return JsonResponse(
        {
            'status': status,
            'business_date': _iso(business_date),
            'generated_at': timezone.localtime(timezone.now()).isoformat(),
            'data_version': data_version,
            'stale': stale,
            'source': source,
            'preparation': {
                'state': preparation_state,
                'retry_after_seconds': retry_after_seconds,
            },
            'warnings': warnings or [],
            'error': error,
            'data': data,
        },
        status=http_status,
    )


def api_success(
    *,
    data: Any,
    business_date: date | None,
    data_version: str | None,
    source: str,
    stale: bool = False,
    warnings: list[str] | None = None,
) -> JsonResponse:
    return api_response(
        status='partial' if warnings else 'ok',
        http_status=200,
        data=data,
        business_date=business_date,
        data_version=data_version,
        stale=stale,
        source=source,
        warnings=warnings,
    )
