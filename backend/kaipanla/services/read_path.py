"""Versioned read path for Kaipanla API responses."""

import logging
from dataclasses import dataclass, replace
from datetime import date
from time import perf_counter
from zoneinfo import ZoneInfo

from django.utils import timezone

from core.api.errors import ApiError, ErrorCode, dataset_busy_error
from backend.env import get_bool_setting, get_required_setting
from core.logging import elapsed_ms, log_event
from core.models import DataVersion
from core.services.locking import DatasetBusy, DatasetLocked, dataset_lock
from core.services.market_data import latest_complete_stock_price_date
from core.services.publication import begin_publication, publish_with_writer
from core.services.cache_keys import build_cache_key
from core.services.file_cache import CachePayloadTooLarge, default_file_cache
from kaipanla.services.client import (
    MAX_PAGE_SIZE,
    KaipanlaRateLimitError,
    KaipanlaSectorFundFlowClient,
    KaipanlaUnavailableError,
    flow_client_settings,
)
from kaipanla.services.fetcher import KaipanlaSectorFundFlowFetcher
from kaipanla.services.history import query_intraday_history
from kaipanla.services.intraday import is_trading_day, query_intraday, resolve_snapshot_slot
from kaipanla.services.queries import list_latest_sectors, published_version_strings
from kaipanla.services.writer import (
    KaipanlaSnapshotWriteResult,
    new_source_batch_id,
    write_complete_snapshot,
)

DATASET_KEY = 'kaipanla_sector_fund_flow'
SHANGHAI_TIME_ZONE = ZoneInfo('Asia/Shanghai')

# 只有"该日已经没救了"才会退回旧快照。下面这些失败说明数据**还在路上**
# （今天正在生成、上游限流/不可用），用旧数据顶掉它们会把一次可观测的上游故障
# 伪装成"数据有点旧"，客户端与运维都会失去线索。
#
# ``SYNC_IN_PROGRESS`` 曾经也在这里，现在不在：数据集被别的任务占用由
# ``DatasetBusy`` 表达，而"有人正在写"恰恰应该先返回旧数据（§5.8a"其余请求立刻
# 返回旧数据或 202"），四个模块在这一点的行为已经完全一致。
_PENDING_REPAIR_CODES = frozenset({
    ErrorCode.DATA_PREPARING,
    ErrorCode.UPSTREAM_RATE_LIMITED,
    ErrorCode.UPSTREAM_UNAVAILABLE,
})

STALE_WARNING = '开盘啦行业资金流快照尚未覆盖最新交易日，正在展示最近一次可用快照。'

# 一次 Web 触发的修复只取一页，而上游单页硬上限就是 ``MAX_PAGE_SIZE``，所以 80 行
# 是这条链路的结构性上限，不是可调策略。
#
# 它以前是 `.env` 里的 ``REMOTE_REPAIR_MAX_ROWS=1000``：单页永远到不了 1000，这道
# 闸门从来不会触发，却和两个真旋钮并排出现在 `.env` 与运维文档里，让人以为行数是
# 可运维的预算。现在它是常量，判断只作为防御性断言保留——只有上游无视 ``st=80``
# 硬塞更多行时才会命中。
REPAIR_MAX_ROWS = MAX_PAGE_SIZE

logger = logging.getLogger(__name__)



@dataclass(frozen=True)
class ReadResult:
    """A successful response plus the version and storage source that served it."""

    data: dict
    business_date: date
    data_version: str
    source: str
    stale: bool = False
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class RepairOutcome:
    """What one bounded repair attempt did, and why it stopped.

    A bare ``bool`` could not carry the reason, so a rate-limited or otherwise
    unreachable upstream was indistinguishable from "today simply has no data
    yet" and every case ended as ``202 DATA_PREPARING`` — a status that invites
    the client to retry into a throttled endpoint.
    """

    published: bool
    upstream_code: ErrorCode | None = None


# 抓取层给出的机器可读失败类型 → 稳定错误码。只有"重试也没用"的两类被映射：
# payload 类失败（上游返回了坏结构）留空，照旧按 202 让客户端稍后再试。
_FETCH_FAILURE_CODES = {
    'rate_limited': ErrorCode.UPSTREAM_RATE_LIMITED,
    'unavailable': ErrorCode.UPSTREAM_UNAVAILABLE,
}


def _positive_setting(name: str) -> int:
    try:
        value = int(get_required_setting(name))
    except ValueError as error:
        raise ValueError(f'{name} must be an integer.') from error
    if value < 1:
        raise ValueError(f'{name} must be positive.')
    return value


def _can_attempt_repair(trade_date: date) -> bool:
    """Only the current Shanghai trading day can be repaired in a web request.

    ``REMOTE_REPAIR_ENABLED`` is a switch, not a budget: a repair is one bounded
    fetch (single page, no retries), so there is no attempt counter to tune —
    the name used to be ``REMOTE_REPAIR_MAX_ATTEMPTS`` and raising it beyond 1
    did nothing.

    The whole chain is tuned by exactly two `.env` knobs: this switch and
    ``REMOTE_REPAIR_HARD_TIMEOUT_SECONDS``. Anything else that used to sit next
    to them (attempts, rows, a "target seconds") was either dead or only a
    retry hint, and read as if it could lengthen the fetch.
    """
    return (
        get_bool_setting('REMOTE_REPAIR_ENABLED', True)
        and trade_date == timezone.localdate(timezone=SHANGHAI_TIME_ZONE)
        and is_trading_day(trade_date)
    )


def _repair_snapshot_time(trade_date: date):
    """Slot a web-triggered repair must write to, or ``None`` when it cannot apply.

    The repair only ever serves the requested day, so a slot that belongs to
    another trading day (before the open, or on a non-trading day) means "today
    has nothing to repair" rather than "write onto the previous close".
    """
    try:
        snapshot_time = resolve_snapshot_slot()
    except ValueError:
        return None
    return snapshot_time if snapshot_time.date() == trade_date else None


def _repair_current_snapshot(trade_date: date) -> RepairOutcome:
    """Try one bounded, current-day upstream fetch and publish it atomically.

    Every exit is logged: this is the only place where a page view triggers an
    upstream request, and "the page said 202 again" is otherwise impossible to
    diagnose from outside (the timeout check, the row guard and the write
    failure all used to look identical — a ``return False``).
    """
    hard_timeout = _positive_setting('REMOTE_REPAIR_HARD_TIMEOUT_SECONDS')
    # 槽位只取决于当前时刻，先算出来：落在别的交易日时根本没有可修复的目标，
    # 直接跳过上游请求，也避免开盘前用前一日数据伪造当天收盘快照。
    snapshot_time = _repair_snapshot_time(trade_date)
    if snapshot_time is None:
        logger.debug(
            '%s trade_date=%s reason=slot_outside_requested_day',
            'repair_skipped',
            trade_date,
        )
        return RepairOutcome(False)
    started_at = perf_counter()
    try:
        with dataset_lock('kaipanla', DATASET_KEY):
            if DataVersion.objects.filter(
                dataset_key=DATASET_KEY,
                business_date=trade_date,
                status=DataVersion.Status.COMPLETE,
            ).exists():
                logger.debug('%s trade_date=%s reason=already_published', 'repair_skipped', trade_date)
                return RepairOutcome(True)

            settings = flow_client_settings()
            # page_size 已由 flow_client_settings 保证不超过 MAX_PAGE_SIZE，所以
            # "一次修复至多一页"不需要在这里再夹一次；行数上限只在下面作为
            # 防御性断言存在。
            settings = replace(
                settings,
                timeout_seconds=min(settings.timeout_seconds, hard_timeout),
                request_delay_seconds=0.0,
            )
            fetch_result = KaipanlaSectorFundFlowFetcher(
                client=KaipanlaSectorFundFlowClient(settings=settings),
                page_size=settings.page_size,
                max_pages=1,
                max_retries=0,
                retry_delay_seconds=0.0,
            ).fetch()
            discard = _repair_discard_reason(
                fetch_result=fetch_result,
                elapsed_seconds=perf_counter() - started_at,
                hard_timeout=hard_timeout,
            )
            if discard is not None:
                reason, upstream_code = discard
                log_event(
                    logger,
                    'repair_discarded',
                    level=logging.WARNING,
                    trade_date=trade_date,
                    duration_ms=elapsed_ms(started_at),
                    reason=reason,
                    rows=len(fetch_result.rows),
                    upstream_complete=fetch_result.is_complete,
                    failure_kind=fetch_result.failure_kind,
                    error_code=upstream_code.value if upstream_code is not None else None,
                )
                return RepairOutcome(False, upstream_code)

            publication = begin_publication(
                'kaipanla', DATASET_KEY, trade_date, len(fetch_result.rows)
            )
            written: KaipanlaSnapshotWriteResult | None = None

            def write_rows() -> None:
                nonlocal written
                written = write_complete_snapshot(
                    fetch_result=fetch_result,
                    snapshot_time=snapshot_time,
                    source_batch_id=new_source_batch_id(),
                    source_data_version=publication.version,
                )

            try:
                # 与采集命令同一条路径：写行与发布同一个 helper，失败处理只有一处，
                # 行上盖着本批次的版本号，未发布的行不会被读出来。
                publish_with_writer(
                    publication,
                    write_rows,
                    actual_record_count=len(fetch_result.rows),
                    missing_record_count=0,
                )
            except Exception as error:
                log_event(
                    logger,
                    'repair_failed',
                    level=logging.ERROR,
                    trade_date=trade_date,
                    snapshot_time=snapshot_time,
                    duration_ms=elapsed_ms(started_at),
                    error=error,
                )
                return RepairOutcome(False)
            cache = default_file_cache()
            if cache is not None:
                cache.invalidate_module('kaipanla')
            log_event(
                logger,
                'repair_published',
                trade_date=trade_date,
                snapshot_time=snapshot_time,
                rows=written.record_count if written is not None else 0,
                duration_ms=elapsed_ms(started_at),
            )
            return RepairOutcome(True)
    except DatasetLocked as error:
        # 锁被占用不再直接变成 409：调用方先看有没有旧快照可返回（§5.8a），
        # 只有"什么都没有"时才是 409 —— 那正是 DatasetBusy 的语义。
        raise DatasetBusy(
            f'The Kaipanla sector fund-flow snapshot for {trade_date.isoformat()} '
            'is being collected.'
        ) from error
    except Exception as error:
        log_event(
            logger,
            'repair_failed',
            level=logging.ERROR,
            trade_date=trade_date,
            duration_ms=elapsed_ms(started_at),
            error=error,
            error_code=upstream_code_for_exception(error),
        )
        return RepairOutcome(False, upstream_code_for_exception(error))


def upstream_code_for_exception(error: BaseException) -> ErrorCode | None:
    """Map this module's own integration errors to the stable upstream codes.

    Duplicated in spirit with ``core.api.errors.upstream_error_code`` on
    purpose: module isolation forbids ``core`` from importing
    ``kaipanla.services.*``, so the business module owns the mapping for its own
    exception classes.
    """
    if isinstance(error, KaipanlaRateLimitError):
        return ErrorCode.UPSTREAM_RATE_LIMITED
    if isinstance(error, KaipanlaUnavailableError):
        return ErrorCode.UPSTREAM_UNAVAILABLE
    return None


def _repair_discard_reason(
    *, fetch_result, elapsed_seconds: float, hard_timeout: int
) -> tuple[str, ErrorCode | None] | None:
    """Why this one-shot repair must not be published, or ``None`` when it may."""
    if elapsed_seconds > hard_timeout:
        return 'hard_timeout_exceeded', None
    if not fetch_result.is_complete:
        return (
            f'upstream_incomplete:{fetch_result.error_summary or "unknown"}',
            _FETCH_FAILURE_CODES.get(fetch_result.failure_kind),
        )
    if not fetch_result.rows:
        return 'upstream_returned_no_rows', None
    # 防御性断言，不是可调预算：修复只取一页，一页最多 REPAIR_MAX_ROWS 行，所以
    # 这一支正常永远不成立。它留在这里是为了在上游无视 st 硬塞更多行时把结果丢掉，
    # 而不是把一批没人预期的行写进快照。
    if len(fetch_result.rows) > REPAIR_MAX_ROWS:
        return 'row_budget_exceeded', None
    return None


def _published_versions():
    return DataVersion.objects.filter(
        dataset_key=DATASET_KEY,
        status=DataVersion.Status.COMPLETE,
        business_date__isnull=False,
    )


def _published_for_date(trade_date: date) -> DataVersion | None:
    """The newest complete version that belongs to exactly ``trade_date``."""
    return (
        _published_versions()
        .filter(business_date=trade_date)
        .order_by('-finished_at', '-started_at')
        .first()
    )


def _newest_published_version() -> DataVersion | None:
    """The newest complete version, whatever business date it belongs to."""
    return (
        _published_versions()
        .order_by('-business_date', '-finished_at', '-started_at')
        .first()
    )


def _published_version(
    trade_date: date | None = None, *, allow_repair: bool = True
) -> DataVersion:
    """Return a complete published version, repairing the current day on demand.

    ``allow_repair=False`` exists for pure metadata endpoints (``/dates/``):
    those are polled by the front end, and a page view must never turn into an
    upstream request just because it asked "which days do you have".
    """
    version = (
        _published_for_date(trade_date)
        if trade_date is not None
        else _newest_published_version()
    )
    if version is not None:
        return version

    if not allow_repair:
        raise ApiError(
            ErrorCode.DATA_NOT_AVAILABLE,
            '请求日期没有可用的完整开盘啦板块资金流数据。',
            http_status=404,
        )

    repair_date = trade_date or timezone.localdate(timezone=SHANGHAI_TIME_ZONE)
    repair_allowed = _can_attempt_repair(repair_date)
    if repair_allowed:
        outcome = _repair_current_snapshot(repair_date)
        if outcome.published:
            return _published_version(repair_date)
        if outcome.upstream_code is not None:
            # 上游限流/不可用是确定性失败：再刷也刷不出来，限流时反复重试只会更糟。
            # 这正是规格里 503 的那一行（无缓存、无库数据 + 远程数据源不可用）。
            log_event(
                logger,
                'read_unavailable',
                level=logging.WARNING,
                dataset_key=DATASET_KEY,
                requested_date=trade_date,
                trade_date=repair_date,
                reason='upstream_unreachable',
                error_code=outcome.upstream_code.value,
            )
            raise ApiError(
                outcome.upstream_code,
                '开盘啦上游数据源暂时不可用，请稍后重试。',
                http_status=503,
                retry_after_seconds=_positive_setting('REMOTE_REPAIR_RETRY_AFTER_SECONDS'),
            )
        # 202：今天确实该有数据，但这一次现场修复没能发布出来 —— 页面的自动刷新
        # 会在下个周期再试，日志要能告诉运维"一直在试、一直没成功"。
        # `retry_after_seconds` 只是给调用方的提示值，不是耗时预算：它不改变上面
        # 那次抓取能花多久（那是 REMOTE_REPAIR_HARD_TIMEOUT_SECONDS 的事）。
        log_event(
            logger,
            'read_preparing',
            level=logging.WARNING,
            dataset_key=DATASET_KEY,
            requested_date=trade_date,
            trade_date=repair_date,
            reason='repair_did_not_publish',
        )
        raise ApiError(
            ErrorCode.DATA_PREPARING,
            '当日开盘啦板块资金流数据正在准备中。',
            http_status=202,
            preparation_state='preparing',
            retry_after_seconds=_positive_setting('REMOTE_REPAIR_RETRY_AFTER_SECONDS'),
        )
    log_event(
        logger,
        'read_unavailable',
        level=logging.WARNING,
        dataset_key=DATASET_KEY,
        requested_date=trade_date,
        repair_allowed=False,
    )
    raise ApiError(
        ErrorCode.DATA_NOT_AVAILABLE,
        '请求日期没有可用的完整开盘啦板块资金流数据。',
        http_status=404,
    )

def _resolve_default_version() -> tuple[DataVersion, bool]:
    """Resolve a request that named no date, plus whether the result is stale.

    The anchor is the same as the three derived modules — the newest complete
    public daily-price date (spec §5.8a) — so all four pages agree on which day
    "the latest" is. A Kaipanla snapshot is collected independently and cannot
    be recomputed from public data, so the newest published snapshot is still
    served when the anchor day has none, flagged ``stale``; that is precisely
    what §5.8.6 prescribes once old data exists, and it is more informative than
    hiding data behind a 404.

    Failures that mean "today's data is still on its way" are **not** masked
    this way (see ``_PENDING_REPAIR_CODES``): a throttled upstream or a running
    sync must stay visible instead of being dressed up as slightly-old data.
    """
    expected = latest_complete_stock_price_date()
    if expected is None:
        # 连"应该有哪天"都还不知道（公共日行情一行都没有）：没有可退回的旧数据，
        # 只能按旧口径试着补当天，把 202 / 503 / 409 如实抛出去。
        return _published_version(), False

    try:
        return _published_version(expected), False
    except (ApiError, DatasetBusy) as error:
        fallback = _newest_published_version()
        if fallback is None:
            raise
        # 上游限流/不可用、今天真的还在准备：这些必须让客户端看见，不能拿旧数据
        # 把一次可观测的上游故障盖掉。数据集被占用（DatasetBusy）不在此列 ——
        # 那份数据此刻正在被写出来，先返回旧数据正是 §5.8a 要求的。
        if isinstance(error, ApiError) and error.code in _PENDING_REPAIR_CODES:
            raise
        log_event(
            logger,
            'read_stale_fallback',
            level=logging.WARNING,
            dataset_key=DATASET_KEY,
            expected_date=expected,
            business_date=fallback.business_date,
            reason='anchor_day_has_no_snapshot',
            error_code=error.code.value if isinstance(error, ApiError) else ErrorCode.SYNC_IN_PROGRESS.value,
        )
        return fallback, True


def _warnings(stale: bool) -> tuple[str, ...]:
    """Explain a stale result in the envelope, not only in the log."""
    return (STALE_WARNING,) if stale else ()


def _read(
    *,
    endpoint: str,
    params: dict[str, object],
    trade_date: date | None,
    query,
) -> ReadResult:
    try:
        if trade_date is not None:
            version, stale = _published_version(trade_date), False
        else:
            version, stale = _resolve_default_version()
    except DatasetBusy as error:
        # 数据集被别的任务占用，而且一条旧快照都没有（§5.7）。有旧快照的情况
        # 上面已经作为 stale 返回了 —— 四个模块在这一点的行为完全一致。
        log_event(
            logger,
            'read_busy',
            level=logging.WARNING,
            dataset_key=DATASET_KEY,
            requested_date=trade_date,
            reason=error,
            error_code=ErrorCode.SYNC_IN_PROGRESS.value,
        )
        raise dataset_busy_error('开盘啦板块资金流正在同步，请稍后重试。') from error
    business_date = version.business_date
    cache = default_file_cache()
    key = build_cache_key('kaipanla', endpoint, params, version.version)

    if cache is not None:
        cached = cache.get(key, version.version)
        if cached is not None:
            return ReadResult(
                cached, business_date, version.version, 'cache', stale, _warnings(stale)
            )

    data = query(business_date)
    if cache is not None:
        try:
            cache.set(key, data, version.version)
        except CachePayloadTooLarge:
            pass
    return ReadResult(
        data, business_date, version.version, 'database', stale, _warnings(stale)
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
                # 只认已发布版本的行：写行与发布分属两个数据库，未发布的行绝不能
                # 被当成"上一个完整版本"的数据返回。
                for row in list_latest_sectors(
                    business_date, published_version_strings([business_date])
                )
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
    """List dates with a complete published Kaipanla snapshot, newest first.

    Kept deliberately free of the repair path: the front end polls this
    endpoint, and "which days do you have" must never spend an upstream request.
    """
    version = _published_version(allow_repair=False)
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
