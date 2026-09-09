"""Authenticated JSON endpoints for the sector-momentum module."""

from django.views.decorators.http import require_GET

from core.api.errors import ApiError, ErrorCode
from core.api.responses import api_success
from core.api.validators import parse_iso_date
from core.services.market_data import CompleteMarketDataUnavailable
from sector_momentum.services.read_path import read_dates, read_sector_momentum


def _require_authenticated(request):
    if not request.user.is_authenticated:
        raise ApiError(ErrorCode.AUTH_REQUIRED, '请先登录。', http_status=401)


def _optional_date(request):
    value = request.GET.get('date')
    return None if value is None else parse_iso_date(value)


def _success(result):
    return api_success(
        data=result.data,
        business_date=result.business_date,
        data_version=result.data_version,
        source=result.source,
        stale=result.stale,
        warnings=list(result.warnings),
    )


def _handle(handler, *, requested_date: bool = False):
    try:
        return handler()
    except CompleteMarketDataUnavailable:
        if requested_date:
            return ApiError(
                ErrorCode.DATA_NOT_AVAILABLE,
                '请求日期没有可用的板块动量数据。',
                http_status=404,
            ).as_response()
        return ApiError(
            ErrorCode.DATA_PREPARING,
            '板块动量数据正在准备中，请先运行管理命令。',
            http_status=202,
            preparation_state='preparing',
        ).as_response()
    except ApiError as error:
        return error.as_response()


@require_GET
def results(request):
    requested_date = 'date' in request.GET
    return _handle(lambda: _results(request), requested_date=requested_date)


def _results(request):
    _require_authenticated(request)
    return _success(read_sector_momentum(_optional_date(request)))


@require_GET
def dates(request):
    return _handle(lambda: _dates(request))


def _dates(request):
    _require_authenticated(request)
    return _success(read_dates())
