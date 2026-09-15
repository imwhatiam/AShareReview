"""Build read-only Kaipanla multi-day close-snapshot payloads."""

from datetime import datetime, time

from django.utils import timezone

from core.services.calendar import recent_trading_days
from kaipanla.services.intraday import validate_ranking_limits
from kaipanla.services.queries import load_close_snapshot_rows

SUPPORTED_HISTORY_WINDOWS = frozenset({1, 5, 10, 20})
CLOSE_TIME = time(15, 0)


def _close_time(trade_date):
    return timezone.make_aware(
        datetime.combine(trade_date, CLOSE_TIME), timezone.get_current_timezone()
    )


def _period_rankings(snapshot_rows, inflow_top, outflow_top):
    totals = {}
    for row in snapshot_rows:
        total = totals.setdefault(
            row['sector_code'],
            {'code': row['sector_code'], 'name': row['sector_name'], 'net_inflow_total': 0.0},
        )
        total['net_inflow_total'] += float(row['main_net_inflow']) / 1e8

    def serialize(item):
        net_inflow_total = round(item['net_inflow_total'], 4)
        return {
            'code': item['code'],
            'name': item['name'],
            'inflow_total': max(net_inflow_total, 0.0),
            'outflow_total': max(-net_inflow_total, 0.0),
            'net_inflow_total': net_inflow_total,
        }

    totals = list(totals.values())
    return {
        'inflows': [serialize(item) for item in sorted(
            totals, key=lambda item: (-item['net_inflow_total'], item['code'])
        )[:inflow_top]],
        'outflows': [serialize(item) for item in sorted(
            totals, key=lambda item: (item['net_inflow_total'], item['code'])
        )[:outflow_top]],
    }


def query_intraday_history(end_date, *, days=5, inflow_top=5, outflow_top=5):
    """Return exact 15:00 records for the public trading-day window and its rankings."""
    if days not in SUPPORTED_HISTORY_WINDOWS:
        raise ValueError('days must be one of 1, 5, 10, or 20.')
    validate_ranking_limits(inflow_top, outflow_top)

    trade_dates = recent_trading_days(end_date, count=days)
    close_times = [_close_time(trade_date) for trade_date in trade_dates]
    snapshot_rows = load_close_snapshot_rows(trade_dates, close_times)
    rankings = _period_rankings(snapshot_rows, inflow_top, outflow_top)
    selected_codes = [
        item['code']
        for direction in ('inflows', 'outflows')
        for item in rankings[direction]
    ]
    selected_codes = list(dict.fromkeys(selected_codes))

    rows_by_date = {}
    for row in snapshot_rows:
        rows_by_date.setdefault(row['trade_date'], {})[row['sector_code']] = row

    missing_trade_dates = []
    items = []
    for trade_date in trade_dates:
        rows_by_code = rows_by_date.get(trade_date, {})
        if not rows_by_code:
            missing_trade_dates.append(str(trade_date))
        items.append({
            'trade_date': str(trade_date),
            'time_points': ['15:00'],
            'series': [
                {
                    'code': code,
                    'name': rows_by_code[code]['sector_name'],
                    'latest_net_inflow': round(
                        float(rows_by_code[code]['main_net_inflow']) / 1e8, 4
                    ),
                    'data': [round(float(rows_by_code[code]['main_net_inflow']) / 1e8, 4)],
                }
                for code in selected_codes
                if code in rows_by_code
            ],
        })

    return {
        'end_date': str(end_date),
        'items': items,
        'period_rankings': rankings,
        'missing_trade_dates': missing_trade_dates,
    }
