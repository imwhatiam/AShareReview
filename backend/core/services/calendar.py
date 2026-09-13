import logging
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

import chinese_calendar
from django.utils import timezone

from core.logging import log_event
from core.models import TradingDay


logger = logging.getLogger(__name__)

SHANGHAI_TIME_ZONE = ZoneInfo('Asia/Shanghai')
MARKET_CLOSE_TIME = time(15, 0)

# 春节、国庆这类连休最长不超过十天，回溯窗口留足余量。
HOLIDAY_LOOKBACK_DAYS = 30

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


def to_shanghai_date(now: datetime | None = None):
    """Return the Asia/Shanghai calendar date of ``now`` (defaults to now)."""
    current = now or timezone.now()
    if timezone.is_naive(current):
        current = timezone.make_aware(current, SHANGHAI_TIME_ZONE)
    return current.astimezone(SHANGHAI_TIME_ZONE).date()


def _is_holiday_free_weekday(day) -> bool:
    """Whether ``day`` is a weekday that is not a statutory holiday."""
    if day.weekday() >= 5:
        return False
    try:
        return not chinese_calendar.is_holiday(day)
    except NotImplementedError:
        # chinese-calendar 按年内置假期表，未覆盖的年份只有工作日信息可用。
        # 退回"工作日即交易日"，但一定要留下痕迹。
        _report_uncovered_year(day)
        return True


def latest_trading_date(now: datetime | None = None):
    """Return the newest date that an exchange history endpoint can serve.

    Distinct from :func:`latest_eligible_trading_day`, which answers "has the
    *current* session already closed". Upstream history endpoints reject a date
    that is not a trading day (开盘啦 industry history answers ``errcode 1020``
    参数出错), so a caller defaulting to "today" fails every weekend and holiday.

    The 同花顺 calendar is authoritative once it reaches the requested date.
    While it lags behind (it is only refreshed up to the last trading day it
    knows about) the statutory holiday table decides instead, so a weekend or
    holiday run still resolves to a date upstream accepts.
    """
    today = to_shanghai_date(now)

    calendar_reaches_today = TradingDay.objects.filter(trade_date__gte=today).exists()
    if calendar_reaches_today:
        synced_day = (
            TradingDay.objects.filter(trade_date__lte=today)
            .order_by('-trade_date')
            .values_list('trade_date', flat=True)
            .first()
        )
        if synced_day is not None:
            return synced_day

    candidate = today
    for _ in range(HOLIDAY_LOOKBACK_DAYS):
        if _is_holiday_free_weekday(candidate):
            return candidate
        candidate -= timedelta(days=1)
    return today


def latest_eligible_trading_day(now: datetime | None = None):
    """Return the latest calendar day eligible for post-close processing."""
    current = now or timezone.now()
    if timezone.is_naive(current):
        current = timezone.make_aware(current, SHANGHAI_TIME_ZONE)
    local_now = current.astimezone(SHANGHAI_TIME_ZONE)
    latest_day = TradingDay.objects.filter(trade_date__lte=local_now.date()).order_by(
        '-trade_date'
    ).first()
    if latest_day is None:
        return None
    if latest_day.trade_date == local_now.date() and local_now.time() < MARKET_CLOSE_TIME:
        latest_day = TradingDay.objects.filter(
            trade_date__lt=local_now.date()
        ).order_by('-trade_date').first()
    return latest_day.trade_date if latest_day is not None else None
