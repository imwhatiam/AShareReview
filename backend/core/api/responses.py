from datetime import date, datetime
from typing import Any

from django.http import JsonResponse
from django.utils import timezone


def _iso(value: date | datetime | None) -> str | None:
    """Serialize a date, or an aware datetime localized to the project timezone.

    The one datetime that travels this way is ``data_updated_at`` — the moment the
    served rows were written — and it comes out of the database in UTC. Sending it
    as ``+00:00`` would be correct and unreadable; localizing first means the
    payload carries a real offset, which the client renders in its own timezone.
    """
    if value is None:
        return None
    if isinstance(value, datetime) and timezone.is_aware(value):
        value = timezone.localtime(value)
    return value.isoformat()


def api_response(
    *,
    status: str,
    http_status: int,
    data: Any = None,
    business_date: date | None = None,
    data_updated_at: datetime | None = None,
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
            # 这份数据是什么时候写进数据库的（不是"这次请求是几点发的"）。
            # 页面工具栏那颗「更新于 HH:MM」显示的就是它，见 core/services/read_path.py。
            'data_updated_at': _iso(data_updated_at),
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
    source: str,
    data_updated_at: datetime | None = None,
    stale: bool = False,
    warnings: list[str] | None = None,
) -> JsonResponse:
    return api_response(
        status='partial' if warnings else 'ok',
        http_status=200,
        data=data,
        business_date=business_date,
        data_updated_at=data_updated_at,
        stale=stale,
        source=source,
        warnings=warnings,
    )
