"""Trading-day resolution.

``chinese-calendar`` is the single source of truth for the A-share trading
calendar. The project used to mirror an upstream REST calendar into a local
``TradingDay`` table and layer the two; that table is gone, so every "is this a
trading day" / "which trading day comes next" question is answered here.
"""

import logging
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import chinese_calendar
from django.utils import timezone

from core.logging import log_event


logger = logging.getLogger(__name__)

SHANGHAI_TIME_ZONE = ZoneInfo('Asia/Shanghai')
MARKET_CLOSE_TIME = time(15, 0)

# A 股连续竞价的上午与下午时段。这是全项目唯一的时段定义：采集命令的
# "默认只在盘中跑" 闸门（`is_trading_session`）与快照归槽
# （`kaipanla.services.intraday`）都从这里取，改时段只改这一处。
#
# `end` 是时段结束的那个钟点，`is_trading_session` 在它上面按**整分钟**判定（见该
# 函数的 docstring）：09:30 / 11:30 / 13:00 / 15:00 这四个整点所在的一分钟都算盘中。
TRADING_SESSIONS = (
    (time(9, 30), time(11, 30)),
    (time(13, 0), time(15, 0)),
)

# 春节、国庆这类连休最长不超过十天，回溯窗口留足余量。
HOLIDAY_LOOKBACK_DAYS = 30

# 一个交易日在自然日上平均占 7/5 天；窗口回溯按这个系数估算，再留一个假期窗口
# 的余量，免得 199 日窗口真的去扫一整年。
_CALENDAR_DAYS_PER_TRADING_DAY = 2

# chinese-calendar 的假期表是按年内置的，未覆盖的年份只能退化成"工作日即交易日"。
# 这个退化方向更宽松、也最危险（法定假日会被当成交易日提交给只服务交易日的上游），
# 所以每年只报一次 WARNING，让"该升级依赖了"出现在日志里而不是靠人去想。
_uncovered_years_reported: set[int] = set()


def _report_uncovered_year(day) -> None:
    if day.year in _uncovered_years_reported:
        return
    _uncovered_years_reported.add(day.year)
    log_event(
        logger,
        'holiday_calendar_uncovered_year',
        level=logging.WARNING,
        year=day.year,
        fallback='weekday_treated_as_trading_day',
        action='upgrade chinese-calendar (requirements.txt) to a release covering this year',
    )


def covered_year_range() -> tuple[int, int]:
    """Return the inclusive ``(first_year, last_year)`` the holiday tables cover.

    ``chinese-calendar`` ships per-year tables and validates by *year*, not by
    date (``chinese_calendar.utils._validate_date``), so a year is either usable
    in full or not usable at all — 2026 counts as covered even though its last
    holiday entry is 2026-10-07.
    """
    years = {day.year for day in chinese_calendar.holidays}
    return min(years), max(years)


def calendar_coverage(now: datetime | None = None) -> dict:
    """Describe how far the bundled holiday tables reach.

    Reported by the health endpoint so the year-boundary cliff is visible
    *before* it is crossed. There is no upstream calendar left to fall back on,
    and the degradation for an uncovered year is the unsafe direction — a
    statutory holiday gets treated as a trading day and submitted to upstream
    endpoints that only serve trading days. The fix is upgrading
    ``chinese-calendar`` in ``requirements.txt``, which has to be scheduled
    ahead of the boundary rather than discovered from a rejected request.
    """
    first_year, last_year = covered_year_range()
    current_year = to_shanghai_date(now).year
    return {
        'covered_from': first_year,
        'covered_through': last_year,
        'covered_through_date': date(last_year, 12, 31).isoformat(),
        'current_year': current_year,
        'current_year_covered': first_year <= current_year <= last_year,
        'next_year_covered': current_year + 1 <= last_year,
    }


def to_shanghai_date(now: datetime | None = None):
    """Return the Asia/Shanghai calendar date of ``now`` (defaults to now)."""
    return _to_shanghai_moment(now).date()


def _to_shanghai_moment(now: datetime | None = None) -> datetime:
    current = now or timezone.now()
    if timezone.is_naive(current):
        current = timezone.make_aware(current, SHANGHAI_TIME_ZONE)
    return current.astimezone(SHANGHAI_TIME_ZONE)


def is_trading_day(day: date) -> bool:
    """Whether ``day`` is an A-share trading day.

    Layered on purpose:

    - Weekends are never trading days. This also covers 调休上班的周末
      ("working" weekends that ``chinese_calendar.is_workday`` reports as
      workdays) — the exchange stays closed on those.
    - Statutory holidays on a weekday come from ``chinese-calendar``, so the
      answer does not depend on any upstream calendar having been synced.
    - ``chinese-calendar`` ships per-year holiday tables. For a year it does not
      cover, the answer degrades to "weekday" and the degradation is reported
      once per year, because mistaking a statutory holiday for a trading day is
      the unsafe direction.
    """
    if day.weekday() >= 5:
        return False
    try:
        return not chinese_calendar.is_holiday(day)
    except NotImplementedError:
        _report_uncovered_year(day)
        return True


def is_trading_session(now: datetime | None = None) -> bool:
    """Whether ``now`` falls inside an A-share continuous trading session.

    Both halves of the guard live together so a caller cannot pick up one
    without the other: the day must be a trading day *and* the clock must be
    inside 09:30-11:30 or 13:00-15:00. The midday break, the pre-open window
    and everything after the close are outside.

    The comparison is made **minute by minute**, so the four boundary clock
    faces — 09:30, 11:30, 13:00, 15:00 — are in session for their whole minute
    (11:30:00.000 through 11:30:59.999). That is deliberate, not sloppy: a
    scheduled collector is started by cron *at* the clock face, and the process
    reads the clock a second or so later (measured: cron fires at 11:30:00.890,
    the Django process evaluates the gate at 11:30:01.304). Treating only the
    exact instant 11:30:00.000000 as inside would make the 11:30 slot
    unreachable forever; the same edge at 15:00 stayed hidden only because a
    separate ``--latest`` cron entry bypasses this gate. The browser-side
    counterpart (``marketSession.js``) has always compared whole minutes, so
    this also aligns the two.

    This is the gate for scheduled collectors that only make sense while the
    exchange is trading — upstream live endpoints serve nothing useful outside
    the session, so a run there is pure noise against the upstream. ``--latest``
    exists precisely to bypass it.
    """
    moment = _to_shanghai_moment(now)
    if not is_trading_day(moment.date()):
        return False
    current_minute = _minute_of_day(moment)
    return any(
        _minute_of_day(start) <= current_minute <= _minute_of_day(end)
        for start, end in TRADING_SESSIONS
    )


def _minute_of_day(value: datetime | time) -> int:
    """Return ``value``'s minute index within its day (00:00 → 0, 15:00 → 900).

    Both ``datetime`` and ``time`` carry ``hour``/``minute``, so the session
    comparison can stay in one unit instead of mixing ``time`` ordering with
    sub-minute arithmetic.
    """
    return value.hour * 60 + value.minute


def latest_trading_day_on_or_before(day: date) -> date:
    """Return the newest trading day that is ``day`` or earlier."""
    candidate = day
    for _ in range(HOLIDAY_LOOKBACK_DAYS):
        if is_trading_day(candidate):
            return candidate
        candidate -= timedelta(days=1)
    raise ValueError(f'No trading day found within {HOLIDAY_LOOKBACK_DAYS} days of {day}.')


def previous_trading_day(day: date) -> date:
    """Return the newest trading day strictly before ``day``."""
    return latest_trading_day_on_or_before(day - timedelta(days=1))


def recent_trading_days(end_date: date, *, count: int) -> list[date]:
    """Return up to ``count`` trading days on or before ``end_date``, newest first."""
    if count <= 0:
        raise ValueError('count must be positive.')
    horizon = count * _CALENDAR_DAYS_PER_TRADING_DAY + HOLIDAY_LOOKBACK_DAYS
    days: list[date] = []
    candidate = end_date
    for _ in range(horizon):
        if len(days) == count:
            break
        if is_trading_day(candidate):
            days.append(candidate)
        candidate -= timedelta(days=1)
    return days


def trading_days_between(start_date: date, end_date: date) -> tuple[date, ...]:
    """Return every trading day in the inclusive range, ascending."""
    if start_date > end_date:
        raise ValueError('start_date must not be after end_date.')
    days: list[date] = []
    candidate = start_date
    while candidate <= end_date:
        if is_trading_day(candidate):
            days.append(candidate)
        candidate += timedelta(days=1)
    return tuple(days)


def latest_trading_date(now: datetime | None = None):
    """Return the newest date that an exchange history endpoint can serve.

    Distinct from :func:`latest_eligible_trading_day`, which answers "has the
    *current* session already closed". Upstream history endpoints reject a date
    that is not a trading day (开盘啦 industry history answers ``errcode 1020``
    参数出错), so a caller defaulting to "today" fails every weekend and holiday.
    """
    return latest_trading_day_on_or_before(to_shanghai_date(now))


def latest_eligible_trading_day(now: datetime | None = None) -> date:
    """Return the latest trading day eligible for post-close processing.

    Before 15:00 the current session has not closed yet, so the answer steps
    back to the previous trading day; on a non-trading day it is the newest
    trading day already behind us.
    """
    local_now = _to_shanghai_moment(now)
    today = local_now.date()
    if not is_trading_day(today):
        return latest_trading_day_on_or_before(today)
    if local_now.time() < MARKET_CLOSE_TIME:
        return previous_trading_day(today)
    return today
