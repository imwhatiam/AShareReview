"""Authenticated JSON endpoints for the Kaipanla business module.

This module builds its handlers by hand instead of calling
``core.api.read_endpoints.build_read_endpoints``: the factory's "this day
cannot be produced" contract is the post-close pair (404 for a named date, 202
for the default entry), while Kaipanla's read path answers ``202 DATA_PREPARING``
for the default entry while today's collection is still in its window and
``404 DATA_NOT_AVAILABLE`` otherwise. It never calls an upstream, so it has no
503 and no 409. The request-side helpers it *does* share — auth, ``?date=``, the
success envelope — come from ``core.api.handlers``.
"""

from django.views.decorators.http import require_GET

from core.api.errors import ApiError
from core.api.handlers import optional_date, require_authenticated, success
from core.api.validators import parse_rank_count, parse_window_days
from kaipanla.services.read_path import (
    read_intraday,
    read_intraday_history,
    read_sectors,
    read_dates,
)


def _rank_count(request, name: str, default: int = 5) -> int:
    return default if name not in request.GET else parse_rank_count(request.GET[name], name)


def _handle(handler):
    try:
        return handler()
    except ApiError as error:
        return error.as_response()


@require_GET
def sectors(request):
    return _handle(lambda: _sectors(request))


def _sectors(request):
    require_authenticated(request)
    return success(read_sectors(optional_date(request)))


@require_GET
def intraday(request):
    return _handle(lambda: _intraday(request))


def _intraday(request):
    require_authenticated(request)
    return success(read_intraday(
        optional_date(request),
        inflow_top=_rank_count(request, 'inflow_top'),
        outflow_top=_rank_count(request, 'outflow_top'),
    ))


@require_GET
def intraday_history(request):
    return _handle(lambda: _intraday_history(request))


def _intraday_history(request):
    require_authenticated(request)
    days = 5 if 'days' not in request.GET else parse_window_days(request.GET['days'])
    return success(read_intraday_history(
        optional_date(request),
        days=days,
        inflow_top=_rank_count(request, 'inflow_top'),
        outflow_top=_rank_count(request, 'outflow_top'),
    ))


@require_GET
def dates(request):
    return _handle(lambda: _dates(request))


def _dates(request):
    require_authenticated(request)
    return success(read_dates())
