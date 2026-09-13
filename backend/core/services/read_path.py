"""Shared cache-first read path for the post-close analysis modules.

``stock_moves``, ``sector_momentum`` and ``hundred_day`` answer their pages the
same way, and the sequence is easy to get subtly wrong:

1. resolve which business date the request should show;
2. look for a stored result whose recorded source versions still match the
   public datasets;
3. regenerate it locally when it is missing or stale;
4. on the default entry only, fall back to the newest stored result marked
   ``stale`` so the first screen still renders;
5. serve it from the file cache when possible, else serialize it and cache it.

Keeping that sequence here — instead of copied into three modules — is what
makes "every module answers the same way" a property of the code rather than
something each module has to remember. A module supplies the parts that are
genuinely its own through :class:`ReadPath`.
"""

import logging
from dataclasses import dataclass
from datetime import date
from time import perf_counter
from typing import Any, Callable

from core.api.errors import ErrorCode, dataset_busy_error
from core.logging import elapsed_ms, log_event
from core.models import DataVersion
from core.services.cache_keys import build_cache_key
from core.services.file_cache import CachePayloadTooLarge
from core.services.locking import DatasetBusy
from core.services.market_data import (
    STOCK_DAILY_PRICES_DATASET,
    CompleteMarketDataUnavailable,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReadResult:
    data: dict
    business_date: date
    data_version: str
    source: str
    stale: bool = False
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReadPath:
    """The module-specific pieces the shared read path cannot know on its own.

    ``results`` returns the module's own default manager with its database alias
    already applied (``Model.objects.using('<module>')``), so this module never
    imports a business model. ``generate`` runs only for a day that has no
    stored result, or whose stored result was built from older public versions.
    The callables are deliberately evaluated at call time from the module's own
    namespace, which is also what keeps ``patch('...services.read_path.X')``
    working in each module's tests.
    """

    module_id: str
    results: Callable[[], Any]
    generate: Callable[[date], Any]
    serialize: Callable[[Any], dict]
    warnings: Callable[[Any, bool], tuple[str, ...]]
    latest_public_date: Callable[[], date | None]
    industry_version: Callable[[], str]
    industry_unavailable: type[BaseException]
    file_cache: Callable[[], Any]
    unavailable_errors: tuple[type[BaseException], ...] = ()
    no_result_message: str = ''


def latest_daily_price_version(business_date: date) -> str | None:
    """The newest complete public daily-price version for one business date."""
    version = DataVersion.objects.filter(
        dataset_key=STOCK_DAILY_PRICES_DATASET,
        business_date=business_date,
        status=DataVersion.Status.COMPLETE,
    ).order_by('-last_success_at', '-started_at').first()
    return version.version if version is not None else None


def latest_result(path: ReadPath) -> Any | None:
    return path.results().order_by('-business_date', '-created_at').first()


def current_source_versions(path: ReadPath, business_date: date) -> tuple[str | None, str | None]:
    """The public versions a result for ``business_date`` should be built from.

    A missing industry snapshot is reported as ``None`` rather than raised: the
    caller turns that into a ``stale`` answer, which is friendlier than failing a
    page whose stored data is still perfectly readable.
    """
    daily_price_version = latest_daily_price_version(business_date)
    try:
        industry_version = path.industry_version()
    except path.industry_unavailable:
        industry_version = None
    return daily_price_version, industry_version


def result_for_date(path: ReadPath, business_date: date) -> tuple[Any | None, bool]:
    """Return the stored result for one day and whether it is out of date."""
    daily_price_version, industry_version = current_source_versions(path, business_date)
    results = path.results().filter(business_date=business_date)
    if daily_price_version is not None and industry_version is not None:
        result = results.filter(
            source_daily_price_version=daily_price_version,
            source_industry_version=industry_version,
        ).order_by('-created_at').first()
        if result is not None:
            return result, False

    result = results.order_by('-created_at').first()
    stale = bool(result and (
        (daily_price_version is not None
         and result.source_daily_price_version != daily_price_version)
        or (industry_version is not None
            and result.source_industry_version != industry_version)
    ))
    return result, stale


def data_version(result: Any) -> str:
    return f'{result.source_daily_price_version}:{result.source_industry_version}'


def resolve_read_date(path: ReadPath, trade_date: date | None) -> date:
    """Pick which day a request without an explicit date should show.

    The newest complete public daily price decides, so the page follows the data
    that actually exists rather than the newest result that happens to be
    stored. When no public daily price is available at all, fall back to the
    newest stored result so the page can still render something.
    """
    if trade_date is not None:
        return trade_date
    latest_public = path.latest_public_date()
    if latest_public is not None:
        return latest_public
    stored = latest_result(path)
    if stored is None:
        raise CompleteMarketDataUnavailable('No complete public daily-price data is available.')
    return stored.business_date


def read(path: ReadPath, trade_date: date | None = None) -> ReadResult:
    """Read a derived result, generating it locally when the requested day has none.

    Logged because a plain page request can silently become a local computation
    (``read_generated``) or silently serve an older day (``read_stale_fallback``);
    the access log alone cannot tell those apart.
    """
    started_at = perf_counter()
    try:
        result = _read(path, trade_date)
    except (CompleteMarketDataUnavailable, *path.unavailable_errors) as error:
        log_event(
            logger,
            'read_unavailable',
            level=logging.WARNING,
            module_id=path.module_id,
            requested_date=trade_date,
            explicit=trade_date is not None,
            duration_ms=elapsed_ms(started_at),
            reason=error,
        )
        raise
    if result.source == 'computed':
        log_event(
            logger,
            'read_generated',
            module_id=path.module_id,
            business_date=result.business_date,
            duration_ms=elapsed_ms(started_at),
            requested_date=trade_date,
        )
    elif result.stale:
        log_event(
            logger,
            'read_stale_fallback',
            level=logging.WARNING,
            module_id=path.module_id,
            business_date=result.business_date,
            requested_date=trade_date,
        )
    else:
        logger.debug(
            '%s business_date=%s source=%s requested_date=%s',
            'read_served',
            result.business_date,
            result.source,
            trade_date,
        )
    return result


def _read(path: ReadPath, trade_date: date | None = None) -> ReadResult:
    requested_explicitly = trade_date is not None
    trade_date = resolve_read_date(path, trade_date)
    result, stale = result_for_date(path, trade_date)
    source = 'database'
    if result is None or stale:
        try:
            result = path.generate(trade_date)
            stale = False
            source = 'computed'
        except (CompleteMarketDataUnavailable, *path.unavailable_errors, DatasetBusy) as error:
            busy = isinstance(error, DatasetBusy)
            if busy:
                # 数据集被别的进程占用（§5.7）。先记一笔：这条路径以前只在
                # 视图层体现成一个状态码，运维看不出"是别人在写"还是"数据没有"。
                log_event(
                    logger,
                    'read_busy',
                    level=logging.WARNING,
                    module_id=path.module_id,
                    business_date=trade_date,
                    requested_date=trade_date if requested_explicitly else None,
                    reason=error,
                    error_code=ErrorCode.SYNC_IN_PROGRESS.value,
                )
            if result is None:
                # 目标日还没有结果、也无法就地生成。显式指定日期时不退回 —— 否则会把
                # 别的日期的数据当成本次请求的结果。
                fallback = None if requested_explicitly else latest_result(path)
                if fallback is None:
                    # 什么都没有：占用是 409 SYNC_IN_PROGRESS（数据正在被写出来），
                    # 其他原因交给视图层按未指定/显式日期回答 202 或 404。
                    if busy:
                        raise dataset_busy_error() from error
                    raise
                # 页面默认入口：退回最近可用的结果并标为旧数据，让首屏仍然可读。
                trade_date = fallback.business_date
                result = fallback
                stale = True

    version = data_version(result)
    cache = path.file_cache()
    key = build_cache_key(path.module_id, 'result', {'date': str(trade_date)}, version)
    if cache is not None and source != 'computed':
        cached = cache.get(key, version)
        if cached is not None:
            return ReadResult(
                cached, result.business_date, version, 'cache', stale,
                path.warnings(result, stale),
            )

    data = path.serialize(result)
    if cache is not None:
        try:
            cache.set(key, data, version)
        except CachePayloadTooLarge:
            pass
    return ReadResult(
        data, result.business_date, version, source, stale, path.warnings(result, stale)
    )


def read_dates(path: ReadPath) -> ReadResult:
    """List the business dates this module has a stored result for."""
    result = latest_result(path)
    if result is None:
        raise CompleteMarketDataUnavailable(path.no_result_message)
    version = data_version(result)
    cache = path.file_cache()
    key = build_cache_key(path.module_id, 'dates', {}, version)
    if cache is not None:
        cached = cache.get(key, version)
        if cached is not None:
            return ReadResult(cached, result.business_date, version, 'cache')

    data = {
        'dates': [
            str(value)
            for value in path.results().order_by('-business_date')
            .values_list('business_date', flat=True).distinct()
        ]
    }
    if cache is not None:
        try:
            cache.set(key, data, version)
        except CachePayloadTooLarge:
            pass
    return ReadResult(data, result.business_date, version, 'database')
