"""Local-only, versioned read path for Eastmoney API responses."""

from dataclasses import dataclass
from datetime import date

from core.api.errors import ApiError, ErrorCode
from core.models import DataVersion, ModuleRunStatus
from core.services.cache_keys import build_cache_key
from core.services.file_cache import CachePayloadTooLarge, default_file_cache
from eastmoney.services.history import query_intraday_history
from eastmoney.services.intraday import query_intraday
from eastmoney.services.queries import (
    latest_snapshot_completeness,
    list_latest_sectors,
)

DATASET_KEY = 'eastmoney_sector_fund_flow'


@dataclass(frozen=True)
class ReadResult:
    """A locally served response plus its version and user-visible warnings."""

    data: dict
    business_date: date
    data_version: str
    source: str
    stale: bool = False
    warnings: tuple[str, ...] = ()


def _published_version(trade_date: date | None = None) -> DataVersion:
    versions = DataVersion.objects.filter(
        dataset_key=DATASET_KEY,
        status__in=(DataVersion.Status.COMPLETE, DataVersion.Status.PARTIAL),
    )
    if trade_date is not None:
        versions = versions.filter(business_date=trade_date)
    version = versions.order_by('-business_date', '-finished_at', '-started_at').first()
    if version is not None and version.business_date is not None:
        return version

    if trade_date is not None:
        raise ApiError(
            ErrorCode.DATA_NOT_AVAILABLE,
            '请求日期没有可用的东方财富板块资金流数据。',
            http_status=404,
        )
    raise ApiError(
        ErrorCode.DATA_PREPARING,
        '东方财富板块资金流数据暂不可用。',
        http_status=202,
        preparation_state='unavailable',
    )


def _is_serving_stale() -> bool:
    status = ModuleRunStatus.objects.filter(
        module_id='eastmoney',
        dataset_key=DATASET_KEY,
    ).first()
    return bool(status and status.serving_stale)


def _warnings(data: dict, version: DataVersion, stale: bool) -> tuple[str, ...]:
    warnings = []
    for direction in data.get('missing_directions', []):
        label = '流入' if direction == 'inflow' else '流出'
        warnings.append(f'东方财富资金流缺少{label}榜数据。')
    if version.status == DataVersion.Status.PARTIAL and not warnings:
        warnings.append('东方财富资金流数据不完整。')
    if stale:
        warnings.append('东方财富上游数据暂不可用，正在展示最近可用数据。')
    return tuple(warnings)


def _read(*, endpoint: str, params: dict[str, object], trade_date: date | None, query) -> ReadResult:
    version = _published_version(trade_date)
    business_date = version.business_date
    stale = _is_serving_stale()
    cache = default_file_cache()
    key = build_cache_key('eastmoney', endpoint, params, version.version)

    if cache is not None:
        cached = cache.get(key, version.version)
        if cached is not None:
            return ReadResult(
                cached,
                business_date,
                version.version,
                'cache',
                stale=stale,
                warnings=_warnings(cached, version, stale),
            )

    data = query(business_date)
    if cache is not None:
        try:
            cache.set(key, data, version.version)
        except CachePayloadTooLarge:
            pass
    return ReadResult(
        data,
        business_date,
        version.version,
        'database',
        stale=stale,
        warnings=_warnings(data, version, stale),
    )


def read_sectors(trade_date: date | None = None) -> ReadResult:
    """Read the most recent sector list for one published business date."""
    params = {'date': str(trade_date)} if trade_date is not None else {}
    return _read(
        endpoint='sectors',
        params=params,
        trade_date=trade_date,
        query=lambda business_date: {
            'trade_date': str(business_date),
            'sectors': [
                {'code': row['sector_code'], 'name': row['sector_name']}
                for row in list_latest_sectors(business_date)
            ],
            **latest_snapshot_completeness(business_date),
        },
    )


def read_intraday(
    trade_date: date | None = None,
    *,
    inflow_top: int = 5,
    outflow_top: int = 5,
) -> ReadResult:
    """Read an intraday chart response from cache or Eastmoney SQLite."""
    params = {
        'date': str(trade_date) if trade_date is not None else None,
        'inflow_top': inflow_top,
        'outflow_top': outflow_top,
    }
    return _read(
        endpoint='sectors/intraday',
        params=params,
        trade_date=trade_date,
        query=lambda business_date: query_intraday(
            business_date,
            inflow_top=inflow_top,
            outflow_top=outflow_top,
        ),
    )


def read_intraday_history(
    trade_date: date | None = None,
    *,
    days: int = 5,
    inflow_top: int = 5,
    outflow_top: int = 5,
) -> ReadResult:
    """Read a multi-day close-snapshot response from cache or Eastmoney SQLite."""
    params = {
        'date': str(trade_date) if trade_date is not None else None,
        'days': days,
        'inflow_top': inflow_top,
        'outflow_top': outflow_top,
    }
    return _read(
        endpoint='sectors/intraday/history',
        params=params,
        trade_date=trade_date,
        query=lambda business_date: query_intraday_history(
            business_date,
            days=days,
            inflow_top=inflow_top,
            outflow_top=outflow_top,
        ),
    )


def read_dates() -> ReadResult:
    """List all published complete or partial Eastmoney business dates."""
    version = _published_version()
    stale = _is_serving_stale()
    cache = default_file_cache()
    key = build_cache_key('eastmoney', 'dates', {}, version.version)
    if cache is not None:
        cached = cache.get(key, version.version)
        if cached is not None:
            return ReadResult(
                cached,
                version.business_date,
                version.version,
                'cache',
                stale=stale,
                warnings=_warnings(cached, version, stale),
            )

    data = {
        'dates': [
            str(business_date)
            for business_date in DataVersion.objects.filter(
                dataset_key=DATASET_KEY,
                status__in=(DataVersion.Status.COMPLETE, DataVersion.Status.PARTIAL),
                business_date__isnull=False,
            ).order_by('-business_date').values_list('business_date', flat=True).distinct()
        ],
    }
    if cache is not None:
        try:
            cache.set(key, data, version.version)
        except CachePayloadTooLarge:
            pass
    return ReadResult(
        data,
        version.business_date,
        version.version,
        'database',
        stale=stale,
        warnings=_warnings(data, version, stale),
    )
