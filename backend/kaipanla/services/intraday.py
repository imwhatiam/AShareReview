"""Build read-only Kaipanla intraday fund-flow payloads."""

from collections import defaultdict
from datetime import datetime, time, timedelta

import chinese_calendar
from django.utils import timezone

from core.models import TradingDay
from kaipanla.services.queries import load_intraday_snapshot_rows, published_version_strings

SNAPSHOT_INTERVAL_MINUTES = 5
TRADING_SESSIONS = (
    (time(9, 30), time(11, 30)),
    (time(13, 0), time(15, 0)),
)
MAX_RANKING_LIMIT = 30


def validate_ranking_limits(inflow_top, outflow_top):
    for parameter_name, value in (
        ('inflow_top', inflow_top),
        ('outflow_top', outflow_top),
    ):
        if not isinstance(value, int) or not 0 <= value <= MAX_RANKING_LIMIT:
            raise ValueError(f'{parameter_name} must be between 0 and {MAX_RANKING_LIMIT}.')


def trading_slots_for_day(trade_date):
    """Return all standard five-minute snapshots in an A-share trading day."""
    time_zone = timezone.get_current_timezone()
    slots = []
    for session_start, session_end in TRADING_SESSIONS:
        current = timezone.make_aware(datetime.combine(trade_date, session_start), time_zone)
        end = timezone.make_aware(datetime.combine(trade_date, session_end), time_zone)
        while current <= end:
            slots.append(current)
            current += timedelta(minutes=SNAPSHOT_INTERVAL_MINUTES)
    return slots


def trading_slots_until(trade_date, now=None):
    """Return standard slots already reached at ``now`` for the requested date."""
    current = now or timezone.now()
    if timezone.is_naive(current):
        current = timezone.make_aware(current, timezone.get_current_timezone())
    local_now = timezone.localtime(current)
    if trade_date > local_now.date():
        return []

    slots = trading_slots_for_day(trade_date)
    if trade_date < local_now.date():
        return slots
    return [slot for slot in slots if slot <= local_now]


def session_slot(moment):
    """Return the last standard slot already reached on ``moment``'s own day.

    ``None`` before that day's opening slot, which lets callers tell
    "no slot of this day has happened yet" apart from "the day is over".
    """
    local_moment = _to_local(moment)
    slots = trading_slots_for_day(local_moment.date())
    reached = [slot for slot in slots if slot <= local_moment]
    return reached[-1] if reached else None


def is_trading_day(trade_date) -> bool:
    """Whether ``trade_date`` is an A-share trading day.

    Layered on purpose:

    - Weekends are never trading days. Note this also covers 调休上班的周末
      ("working" weekends that ``chinese_calendar.is_workday`` reports as
      workdays) — the exchange stays closed on those.
    - Statutory holidays come from ``chinese-calendar``, so the answer no longer
      depends on whether the 同花顺 trading calendar happens to have been synced
      for that date yet. That matters for the write path: mistaking a trading day
      for a holiday would write today's intraday data onto the previous trading
      day's close.
    - When ``chinese-calendar`` has no data for that year (it ships per-year
      holiday tables), fall back to the 同花顺 calendar, which stays the
      authoritative record of historical trading days.
    """
    if trade_date.weekday() >= 5:
        return False
    holiday = _statutory_holiday(trade_date)
    if holiday is None:
        return _synced_calendar_says_trading_day(trade_date)
    return not holiday


def _statutory_holiday(trade_date):
    """``True``/``False`` for a holiday, or ``None`` when the year has no data."""
    try:
        return chinese_calendar.is_holiday(trade_date)
    except NotImplementedError:
        return None


def _synced_calendar_says_trading_day(trade_date) -> bool:
    """Read the 同花顺 trading calendar; assume a trading day when it ends before the date."""
    if TradingDay.objects.filter(trade_date=trade_date).exists():
        return True
    return not TradingDay.objects.filter(trade_date__gte=trade_date).exists()


def previous_close_slot(trade_date):
    """Return the 15:00 slot of the most recent trading day before ``trade_date``."""
    previous_day = (
        TradingDay.objects.filter(trade_date__lt=trade_date)
        .order_by('-trade_date')
        .values_list('trade_date', flat=True)
        .first()
    )
    if previous_day is None:
        raise ValueError('缺少交易日历数据，无法确定快照归属的交易日。')
    return trading_slots_for_day(previous_day)[-1]


def resolve_snapshot_slot(moment=None):
    """Map a collection moment onto the standard five-minute slot it must be stored at.

    One rule for every write path (scheduled run, `--latest`, web repair):

    - On a trading day the snapshot belongs to the last slot already reached:
      inside a session the moment floors onto its own five-minute slot
      (09:33 → 09:30, 10:46 → 10:45, 14:22 → 14:20); the midday break floors onto
      the morning close (12:20 → 11:30); after the close everything lands on
      15:00 (16:34 → 15:00), so a later run simply refreshes the close snapshot.
    - On a non-trading day, and before a trading day opens, the freshest complete
      data is the previous trading day's close, so the snapshot belongs to that
      day's 15:00 slot and overwrites it.
    """
    local_moment = _to_local(moment or timezone.now())
    if is_trading_day(local_moment.date()):
        slot = session_slot(local_moment)
        if slot is not None:
            return slot
    return previous_close_slot(local_moment.date())


def _to_local(moment):
    if timezone.is_naive(moment):
        moment = timezone.make_aware(moment, timezone.get_current_timezone())
    return timezone.localtime(moment)


def _build_series(snapshot_rows, time_axis, inflow_top, outflow_top):
    values_by_sector = defaultdict(dict)
    names_by_sector = {}
    for row in snapshot_rows:
        code = row['sector_code']
        names_by_sector[code] = row['sector_name']
        values_by_sector[code][row['snapshot_time']] = float(row['main_net_inflow']) / 1e8

    if not values_by_sector:
        return []

    source_time = next(
        (
            slot for slot in reversed(time_axis)
            if any(slot in values for values in values_by_sector.values())
        ),
        None,
    )
    if source_time is None:
        return []

    source_codes = [
        code for code, values in values_by_sector.items() if source_time in values
    ]
    series = []
    for code in source_codes:
        values = values_by_sector[code]
        last_value = 0.0
        data = []
        for slot in time_axis:
            if slot in values:
                last_value = values[slot]
            data.append(round(last_value, 4))
        series.append({
            'code': code,
            'name': names_by_sector[code],
            'latest_net_inflow': round(values[source_time], 4),
            'data': data,
        })

    inflows = sorted(
        (item for item in series if item['latest_net_inflow'] > 0),
        key=lambda item: (-item['latest_net_inflow'], item['code']),
    )[:inflow_top]
    outflows = sorted(
        (item for item in series if item['latest_net_inflow'] < 0),
        key=lambda item: (item['latest_net_inflow'], item['code']),
    )[:outflow_top]
    return inflows + outflows


def query_intraday(trade_date, *, inflow_top=5, outflow_top=5, now=None):
    """Return a five-minute axis and the positive/negative ranked sector curves."""
    validate_ranking_limits(inflow_top, outflow_top)
    time_axis = trading_slots_until(trade_date, now=now)
    if not time_axis:
        return {'trade_date': str(trade_date), 'time_points': [], 'series': []}

    snapshot_rows = load_intraday_snapshot_rows(
        trade_date, time_axis, published_version_strings([trade_date])
    )
    series = _build_series(snapshot_rows, time_axis, inflow_top, outflow_top)
    if not series:
        return {'trade_date': str(trade_date), 'time_points': [], 'series': []}
    return {
        'trade_date': str(trade_date),
        'time_points': [timezone.localtime(slot).strftime('%H:%M') for slot in time_axis],
        'series': series,
    }
