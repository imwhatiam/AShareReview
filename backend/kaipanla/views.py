"""Authenticated JSON endpoints for the Kaipanla business module."""

from django.views.decorators.http import require_GET

from core.api.errors import ApiError, ErrorCode
from core.api.responses import api_success
from core.api.validators import parse_iso_date, parse_rank_count, parse_window_days
from kaipanla.services.read_path import (
    read_intraday,
    read_intraday_history,
    read_sectors,
    read_dates,
)


def _require_authenticated(request):
    if not request.user.is_authenticated:
        raise ApiError(ErrorCode.AUTH_REQUIRED, '请先登录。', http_status=401)


def _optional_date(request):
    value = request.GET.get('date')
    return None if value is None else parse_iso_date(value)


def _rank_count(request, name: str, default: int = 5) -> int:
    return default if name not in request.GET else parse_rank_count(request.GET[name], name)


def _success(result):
    return api_success(
        data=result.data,
        business_date=result.business_date,
        data_version=result.data_version,
        source=result.source,
        stale=result.stale,
        warnings=list(result.warnings),
    )


def _handle(handler):
    try:
        return handler()
    except ApiError as error:
        return error.as_response()


@require_GET
def sectors(request):
    return _handle(lambda: _sectors(request))


def _sectors(request):
    _require_authenticated(request)
    return _success(read_sectors(_optional_date(request)))


@require_GET
def intraday(request):
    return _handle(lambda: _intraday(request))


def _intraday(request):
    _require_authenticated(request)
    return _success(read_intraday(
        _optional_date(request),
        inflow_top=_rank_count(request, 'inflow_top'),
        outflow_top=_rank_count(request, 'outflow_top'),
    ))


@require_GET
def intraday_history(request):
    return _handle(lambda: _intraday_history(request))


def _intraday_history(request):
    _require_authenticated(request)
    days = 5 if 'days' not in request.GET else parse_window_days(request.GET['days'])
    return _success(read_intraday_history(
        _optional_date(request),
        days=days,
        inflow_top=_rank_count(request, 'inflow_top'),
        outflow_top=_rank_count(request, 'outflow_top'),
    ))


@require_GET
def dates(request):
    return _handle(lambda: _dates(request))


def _dates(request):
    _require_authenticated(request)
    return _success(read_dates())
