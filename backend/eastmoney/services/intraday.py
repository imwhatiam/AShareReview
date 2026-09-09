"""Build read-only Eastmoney intraday fund-flow payloads."""

from collections import defaultdict
from datetime import datetime, time, timedelta

from django.utils import timezone

from eastmoney.services.queries import load_intraday_snapshot_rows, query_completeness

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


def _build_series(snapshot_rows, time_axis, inflow_top, outflow_top):
    values_by_sector = defaultdict(dict)
    names_by_sector = {}
    batch_ids_by_sector = defaultdict(dict)
    for row in snapshot_rows:
        value = row['main_net_inflow']
        if value is None:
            continue
        code = row['sector_code']
        names_by_sector[code] = row['sector_name']
        values_by_sector[code][row['snapshot_time']] = float(value) / 1e8
        batch_ids_by_sector[code][row['snapshot_time']] = row['source_batch_id']

    if not values_by_sector:
        return [], []

    source_time = next(
        (
            slot for slot in reversed(time_axis)
            if any(slot in values for values in values_by_sector.values())
        ),
        None,
    )
    if source_time is None:
        return [], []

    source_codes = [
        code for code, values in values_by_sector.items() if source_time in values
    ]
    series = []
    source_batch_ids = []
    for code in source_codes:
        values = values_by_sector[code]
        source_batch_ids.append(batch_ids_by_sector[code][source_time])
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
    return inflows + outflows, source_batch_ids


def query_intraday(trade_date, *, inflow_top=5, outflow_top=5, now=None):
    """Return a five-minute axis and the positive/negative ranked sector curves."""
    validate_ranking_limits(inflow_top, outflow_top)
    time_axis = trading_slots_until(trade_date, now=now)
    if not time_axis:
        return {
            'trade_date': str(trade_date),
            'time_points': [],
            'series': [],
            'completeness': 'complete',
            'missing_directions': [],
        }

    snapshot_rows = load_intraday_snapshot_rows(trade_date, time_axis)
    series, source_batch_ids = _build_series(
        snapshot_rows, time_axis, inflow_top, outflow_top
    )
    if not series:
        return {
            'trade_date': str(trade_date),
            'time_points': [],
            'series': [],
            **query_completeness(source_batch_ids),
        }
    return {
        'trade_date': str(trade_date),
        'time_points': [timezone.localtime(slot).strftime('%H:%M') for slot in time_axis],
        'series': series,
        **query_completeness(source_batch_ids),
    }
