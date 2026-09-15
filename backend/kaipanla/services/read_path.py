"""Read path for the Kaipanla sector fund-flow API.

The module owns **one database and one table**: a crontab-driven management
command collects the sectors from the upstream every five minutes and writes
``KaipanlaSectorFundFlowSnapshot`` rows; this read path answers every request out
of those rows, from the file cache when it can. That is the whole design.

Three things are deliberately absent, because each of them used to cost more
than it bought:

* **No write on read.** A page request never calls the upstream. When the newest
  stored trading day is behind the newest day that should have a snapshot, the
  request either gets the newest stored day marked ``stale`` (the honest
  "正在展示旧数据") or ``202 DATA_PREPARING`` while today's collection is still
  plausibly on its way. Failures belong to the command log, not to a page view.
* **No second database.** The module keeps its rows in its own database and
  nothing in the core database. A collection writes its rows and the commit *is*
  the publication, so every read answers from whatever rows exist — there is no
  published/unpublished distinction to filter by.
* **No run table.** One collection = one ``INSERT ... ON CONFLICT DO UPDATE``.
  How many rows the upstream claimed, how many arrived and which page failed are
  log fields on the command, not table columns.

What ``stale`` means here, and nothing else: the newest stored snapshot is behind
the newest trading day that should already have one.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.utils import timezone

from core.api.errors import ApiError, ErrorCode
from core.logging import log_event
from core.services.cache_keys import build_cache_key
from core.services.calendar import (
    TRADING_SESSIONS,
    is_trading_day,
    latest_trading_day_on_or_before,
    previous_trading_day,
)
from core.services.file_cache import CachePayloadTooLarge, default_file_cache
from kaipanla.services.history import query_intraday_history
from kaipanla.services.intraday import query_intraday
from kaipanla.services.queries import (
    latest_snapshot,
    latest_trade_date,
    list_latest_sectors,
    list_trade_dates,
)

SHANGHAI_TIME_ZONE = ZoneInfo('Asia/Shanghai')

STALE_WARNING = '开盘啦行业资金流快照尚未覆盖最新交易日，正在展示最近一次可用快照。'
NO_SNAPSHOT_MESSAGE = '请求日期没有可用的开盘啦板块资金流快照。'

# 交易日的第一个快照就落在开盘那一槽（`trading_slots_for_day` 的起点），所以开盘前
# "该有快照的最新交易日"仍要退回上一个交易日。取值直接来自时段定义，不写字面量。
FIRST_SNAPSHOT_TIME = TRADING_SESSIONS[0][0]
# 最后一个时段的收盘钟点。过了它，"今天还没有快照"就不再是"数据还在路上"，而是
# "今天不会有数据了"——那时应当如实返回旧数据，而不是一直说"准备中"。
LAST_SNAPSHOT_TIME = TRADING_SESSIONS[-1][1]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReadResult:
    """A successful response plus the identity and storage source that served it."""

    data: dict
    business_date: date
    cache_identity: str
    source: str
    stale: bool = False
    warnings: tuple[str, ...] = ()
    # 这批快照写进数据库的时刻（最新槽那批行的 `created_at`）。页面工具栏的
    # 「更新于 HH:MM」显示它 —— 快照每 5 分钟采一次，它是"页面上的资金流有多新"
    # 的唯一答案，而这与"用户几点打开页面"无关。
    data_updated_at: datetime | None = None


def _now():
    return timezone.localtime(timezone.now(), SHANGHAI_TIME_ZONE)


def _latest_expected_snapshot_date() -> date:
    """The newest trading day that should already have a collected snapshot.

    A trading day gets its first snapshot from the opening five-minute slot
    (09:30), so before the open the newest day that *can* have one is still the
    previous trading day; on a non-trading day it is the newest trading day
    behind us. This is the only clock-dependent piece of the default entry, and
    it is what gives ``stale`` its meaning: the newest snapshot is behind it.

    Deliberately **not** ``latest_eligible_trading_day``: that one answers "has
    *today's* session closed" for the post-close pipeline, which would make the
    page wait until 15:00 before it may follow today at all.
    """
    moment = _now()
    today = moment.date()
    if not is_trading_day(today):
        return latest_trading_day_on_or_before(today)
    if moment.time() < FIRST_SNAPSHOT_TIME:
        return previous_trading_day(today)
    return today


def _today_is_still_collecting() -> bool:
    """Whether "today has no snapshot" can still mean "it is on its way".

    Only between the open and the close of the day's last session. Once that
    moment has passed, a missing today is a missing today: the page should say
    "正在展示旧数据" instead of promising a preparation that is not happening.
    """
    moment = _now()
    return is_trading_day(moment.date()) and moment.time() < LAST_SNAPSHOT_TIME


def _identity(trade_date: date, newest_slot) -> str:
    """The cache identity of one business day: its newest collected slot.

    It changes exactly when new data lands, which is the only thing that may
    invalidate a cached payload — so a cached body can never outlive the rows it
    was built from.
    """
    local_slot = timezone.localtime(newest_slot, SHANGHAI_TIME_ZONE)
    return f'kaipanla:{trade_date.isoformat()}T{local_slot:%H:%M}'


def _resolve_default_date() -> tuple[date, bool]:
    """Pick which business date a request without ``?date=`` should show.

    The anchor is **this module's own newest stored snapshot**, not the newest
    complete public daily-price date the three derived modules use. A fund-flow
    snapshot cannot be computed from public data — it is collected straight from
    the upstream during the session — so it is routinely fresher than
    ``stock_daily_prices``: the collector writes 09:35 while the intraday-quote
    chain publishes today's public prices later, or never at all when that chain
    is not scheduled. Anchoring on the public date made the page show the
    *previous* trading day while a same-day snapshot was already in the database.

    Returns ``(business_date, stale)``. ``stale`` is true only in the one case
    that deserves a warning: the newest stored day is behind the newest day that
    should already have a snapshot (a gap the collector has not filled). While
    today's collection is still in its window, that same situation answers
    ``202`` instead, so the client retries rather than being shown yesterday as
    if it were today.
    """
    expected = _latest_expected_snapshot_date()
    newest = latest_trade_date()
    if newest is None:
        # 一条快照都没有：没有可以退回去的旧数据，如实说没有。
        log_event(
            logger,
            'read_unavailable',
            level=logging.WARNING,
            expected_date=expected,
            reason='no_snapshot_at_all',
        )
        raise ApiError(ErrorCode.DATA_NOT_AVAILABLE, NO_SNAPSHOT_MESSAGE, http_status=404)

    if newest >= expected:
        return newest, False

    if expected == _now().date() and _today_is_still_collecting():
        log_event(
            logger,
            'read_preparing',
            level=logging.WARNING,
            expected_date=expected,
            business_date=newest,
            reason='today_not_collected_yet',
        )
        raise ApiError(
            ErrorCode.DATA_PREPARING,
            '当日开盘啦板块资金流数据正在准备中。',
            http_status=202,
            preparation_state='preparing',
        )

    log_event(
        logger,
        'read_stale_fallback',
        level=logging.WARNING,
        expected_date=expected,
        business_date=newest,
        reason='latest_trading_day_has_no_snapshot',
    )
    return newest, True


def _warnings(stale: bool) -> tuple[str, ...]:
    """Explain a stale result in the envelope, not only in the log."""
    return (STALE_WARNING,) if stale else ()


def _explicit_or_default_date(trade_date: date | None) -> tuple[date, bool, object, object]:
    """Resolve the served day, its newest slot, when that slot landed, and staleness.

    An explicitly requested date is **never** substituted: a day with no rows is
    ``404``, not "some other day's data". Only the default entry may fall back to
    a day it actually has.
    """
    if trade_date is None:
        business_date, stale = _resolve_default_date()
    else:
        business_date, stale = trade_date, False
    newest_slot, written_at = latest_snapshot(business_date)
    if newest_slot is None:
        log_event(
            logger,
            'read_unavailable',
            level=logging.WARNING,
            requested_date=trade_date,
            explicit=trade_date is not None,
            reason='no_snapshot_for_date',
        )
        raise ApiError(ErrorCode.DATA_NOT_AVAILABLE, NO_SNAPSHOT_MESSAGE, http_status=404)
    return business_date, stale, newest_slot, written_at


def _read(
    *,
    endpoint: str,
    params: dict[str, object],
    trade_date: date | None,
    query,
) -> ReadResult:
    business_date, stale, newest_slot, written_at = _explicit_or_default_date(trade_date)
    identity = _identity(business_date, newest_slot)
    cache = default_file_cache()
    key = build_cache_key('kaipanla', endpoint, params, identity)

    if cache is not None:
        cached = cache.get(key, identity)
        if cached is not None:
            return ReadResult(
                cached, business_date, identity, 'cache', stale, _warnings(stale), written_at
            )

    data = query(business_date)
    if cache is not None:
        try:
            cache.set(key, data, identity)
        except CachePayloadTooLarge:
            pass
    return ReadResult(
        data, business_date, identity, 'database', stale, _warnings(stale), written_at
    )


def read_sectors(trade_date: date | None = None) -> ReadResult:
    """Read the most recent sector list for one business date."""
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
    """Read the day's whole-session chart response from cache or local SQLite."""
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
    """Read the multi-day close-snapshot response from cache or local SQLite."""
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
    """List every business date with stored snapshots, newest first."""
    newest = latest_trade_date()
    if newest is None:
        raise ApiError(ErrorCode.DATA_NOT_AVAILABLE, NO_SNAPSHOT_MESSAGE, http_status=404)
    newest_slot, written_at = latest_snapshot(newest)
    identity = _identity(newest, newest_slot)
    cache = default_file_cache()
    key = build_cache_key('kaipanla', 'dates', {}, identity)
    if cache is not None:
        cached = cache.get(key, identity)
        if cached is not None:
            return ReadResult(cached, newest, identity, 'cache', data_updated_at=written_at)

    data = {'dates': [str(value) for value in list_trade_dates()]}
    if cache is not None:
        try:
            cache.set(key, data, identity)
        except CachePayloadTooLarge:
            pass
    return ReadResult(data, newest, identity, 'database', data_updated_at=written_at)
