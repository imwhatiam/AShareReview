"""Versioned read path for Kaipanla API responses."""

from dataclasses import dataclass, replace
from datetime import date, datetime
from math import ceil
from time import monotonic
from zoneinfo import ZoneInfo

from django.utils import timezone

from core.api.errors import ApiError, ErrorCode
from backend.env import get_required_setting
from core.models import DataVersion
from core.services.locking import DatasetLocked, dataset_lock
from core.services.publication import begin_publication, fail_publication, finish_publication
from core.services.cache_keys import build_cache_key
from core.services.file_cache import CachePayloadTooLarge, default_file_cache
from kaipanla.services.client import KaipanlaSectorFundFlowClient, flow_client_settings
from kaipanla.services.fetcher import KaipanlaSectorFundFlowFetcher
from kaipanla.services.history import query_intraday_history
from kaipanla.services.intraday import query_intraday
from kaipanla.services.queries import list_latest_sectors
from kaipanla.services.writer import new_source_batch_id, write_complete_snapshot

DATASET_KEY = 'kaipanla_sector_fund_flow'
SHANGHAI_TIME_ZONE = ZoneInfo('Asia/Shanghai')



@dataclass(frozen=True)
class ReadResult:
    """A successful response plus the version and storage source that served it."""

    data: dict
    business_date: date
    data_version: str
    source: str
    stale: bool = False
    warnings: tuple[str, ...] = ()


def _positive_setting(name: str) -> int:
    try:
        value = int(get_required_setting(name))
    except ValueError as error:
        raise ValueError(f'{name} must be an integer.') from error
    if value < 1:
        raise ValueError(f'{name} must be positive.')
    return value


def _can_attempt_repair(trade_date: date) -> bool:
    """Only the current Shanghai trading day can be repaired in a web request."""
    return (
        _positive_setting('REMOTE_REPAIR_MAX_ATTEMPTS') >= 1
        and trade_date == timezone.localdate(timezone=SHANGHAI_TIME_ZONE)
    )


def _repair_snapshot_time(fetch_result, requested_date: date):
    try:
        timestamp = int(fetch_result.source_timestamp)
    except (TypeError, ValueError):
        return None
    if timestamp > 10**11:
        timestamp //= 1000
    snapshot_time = datetime.fromtimestamp(timestamp, SHANGHAI_TIME_ZONE)
    snapshot_time = snapshot_time.replace(
        minute=(snapshot_time.minute // 5) * 5, second=0, microsecond=0
    )
    return snapshot_time if snapshot_time.date() == requested_date else None


def _repair_current_snapshot(trade_date: date) -> bool:
    """Try one bounded, current-day upstream fetch and publish it atomically."""
    hard_timeout = _positive_setting('REMOTE_REPAIR_HARD_TIMEOUT_SECONDS')
    max_rows = _positive_setting('REMOTE_REPAIR_MAX_ROWS')
    started_at = monotonic()
    try:
        with dataset_lock('kaipanla', DATASET_KEY):
            if DataVersion.objects.filter(
                dataset_key=DATASET_KEY,
                business_date=trade_date,
                status=DataVersion.Status.COMPLETE,
            ).exists():
                return True

            settings = flow_client_settings()
            page_size = min(settings.page_size, max_rows)
            settings = replace(
                settings,
                page_size=page_size,
                timeout_seconds=min(settings.timeout_seconds, hard_timeout),
                request_delay_seconds=0.0,
            )
            fetch_result = KaipanlaSectorFundFlowFetcher(
                client=KaipanlaSectorFundFlowClient(settings=settings),
                page_size=page_size,
                max_pages=1,
                max_retries=0,
                retry_delay_seconds=0.0,
            ).fetch()
            snapshot_time = _repair_snapshot_time(fetch_result, trade_date)
            if (
                monotonic() - started_at > hard_timeout
                or not fetch_result.is_complete
                or not fetch_result.rows
                or len(fetch_result.rows) > max_rows
                or snapshot_time is None
            ):
                return False

            publication = begin_publication(
                'kaipanla', DATASET_KEY, trade_date, len(fetch_result.rows)
            )
            try:
                write_result = write_complete_snapshot(
                    fetch_result=fetch_result,
                    snapshot_time=snapshot_time,
                    source_batch_id=new_source_batch_id(),
                )
                finish_publication(publication, write_result.record_count, 0)
            except Exception as error:
                fail_publication(publication, error)
                return False
            cache = default_file_cache()
            if cache is not None:
                cache.invalidate_module('kaipanla')
            return True
    except DatasetLocked as error:
        raise ApiError(
            ErrorCode.SYNC_IN_PROGRESS,
            '开盘啦板块资金流正在同步，请稍后重试。',
            http_status=409,
            preparation_state='syncing',
        ) from error
    except Exception:
        return False


def _published_version(trade_date: date | None = None) -> DataVersion:
    versions = DataVersion.objects.filter(
        dataset_key=DATASET_KEY,
        status=DataVersion.Status.COMPLETE,
    )
    if trade_date is not None:
        versions = versions.filter(business_date=trade_date)
    version = versions.order_by('-business_date', '-finished_at', '-started_at').first()
    if version is not None and version.business_date is not None:
        return version

    repair_date = trade_date or timezone.localdate(timezone=SHANGHAI_TIME_ZONE)
    repair_allowed = _can_attempt_repair(repair_date)
    if repair_allowed and _repair_current_snapshot(repair_date):
        return _published_version(repair_date)
    if repair_allowed:
        raise ApiError(
            ErrorCode.DATA_PREPARING,
            '当日开盘啦板块资金流数据正在准备中。',
            http_status=202,
            preparation_state='preparing',
            retry_after_seconds=_positive_setting('REMOTE_REPAIR_TARGET_SECONDS'),
        )
    raise ApiError(
        ErrorCode.DATA_NOT_AVAILABLE,
        '请求日期没有可用的完整开盘啦板块资金流数据。',
        http_status=404,
    )

def _read(
    *,
    endpoint: str,
    params: dict[str, object],
    trade_date: date | None,
    query,
) -> ReadResult:
    version = _published_version(trade_date)
    business_date = version.business_date
    cache = default_file_cache()
    key = build_cache_key('kaipanla', endpoint, params, version.version)

    if cache is not None:
        cached = cache.get(key, version.version)
        if cached is not None:
            return ReadResult(cached, business_date, version.version, 'cache')

    data = query(business_date)
    if cache is not None:
        try:
            cache.set(key, data, version.version)
        except CachePayloadTooLarge:
            pass
    return ReadResult(data, business_date, version.version, 'database')


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
        },
    )


def read_intraday(
    trade_date: date | None = None,
    *,
    inflow_top: int = 5,
    outflow_top: int = 5,
) -> ReadResult:
    """Read a versioned intraday chart response from cache or local SQLite."""
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
    """Read a versioned multi-day close-snapshot response from cache or SQLite."""
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
    """List dates with a complete published Kaipanla snapshot, newest first."""
    version = _published_version()
    cache = default_file_cache()
    key = build_cache_key('kaipanla', 'dates', {}, version.version)
    if cache is not None:
        cached = cache.get(key, version.version)
        if cached is not None:
            return ReadResult(cached, version.business_date, version.version, 'cache')

    data = {
        'dates': [
            str(business_date)
            for business_date in DataVersion.objects.filter(
                dataset_key=DATASET_KEY,
                status=DataVersion.Status.COMPLETE,
                business_date__isnull=False,
            ).order_by('-business_date').values_list('business_date', flat=True).distinct()
        ],
    }
    if cache is not None:
        try:
            cache.set(key, data, version.version)
        except CachePayloadTooLarge:
            pass
    return ReadResult(data, version.business_date, version.version, 'database')
