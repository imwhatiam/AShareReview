"""Build read-only Kaipanla intraday fund-flow payloads.

The intraday axis always spans the **whole** trading session (09:30–11:30 plus
13:00–15:00, one slot every five minutes): a page opened at 10:00, during the
midday break or after the close must show the same time scale, so the axis is
never cut at "the slots reached so far". "Today is not over yet" is expressed by
each curve instead — ``data`` only covers the slots collected up to the newest
snapshot (see ``_build_series``). The query moment therefore never enters the
payload: it is a pure function of the business date and the rows stored for it.
"""

from collections import defaultdict
from datetime import datetime, timedelta

from django.utils import timezone

from core.services.calendar import TRADING_SESSIONS, is_trading_day, previous_trading_day
from kaipanla.services.queries import load_intraday_snapshot_rows

SNAPSHOT_INTERVAL_MINUTES = 5
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


def session_slot(moment):
    """Return the last standard slot already reached on ``moment``'s own day.

    ``None`` before that day's opening slot, which lets callers tell
    "no slot of this day has happened yet" apart from "the day is over".
    """
    local_moment = _to_local(moment)
    slots = trading_slots_for_day(local_moment.date())
    reached = [slot for slot in slots if slot <= local_moment]
    return reached[-1] if reached else None


def previous_close_slot(trade_date):
    """Return the 15:00 slot of the most recent trading day before ``trade_date``."""
    return trading_slots_for_day(previous_trading_day(trade_date))[-1]


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
    # 曲线只画到最后一个已采集的时点：整条交易时段是横轴的**范围**，不是曲线的长度。
    # 往后补值（无论是复制最后一个值还是补 None）都会把"还没收盘"画成一条已知的线。
    collected_axis = time_axis[: time_axis.index(source_time) + 1]
    series = []
    for code in source_codes:
        values = values_by_sector[code]
        last_value = 0.0
        data = []
        for slot in collected_axis:
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


def query_intraday(trade_date, *, inflow_top=5, outflow_top=5):
    """Return the day's whole-session axis and the ranked sector curves."""
    validate_ranking_limits(inflow_top, outflow_top)
    time_axis = trading_slots_for_day(trade_date)
    snapshot_rows = load_intraday_snapshot_rows(trade_date, time_axis)
    series = _build_series(snapshot_rows, time_axis, inflow_top, outflow_top)
    if not series:
        return {'trade_date': str(trade_date), 'time_points': [], 'series': []}
    return {
        'trade_date': str(trade_date),
        'time_points': [timezone.localtime(slot).strftime('%H:%M') for slot in time_axis],
        'series': series,
    }
