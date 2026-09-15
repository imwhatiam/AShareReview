"""Read-only ORM queries for the independently stored Kaipanla snapshots.

Every function here reads one database — this module's own. There is no
cross-database lookup and no "is it published" filter: the rows in
``kaipanla.sqlite3`` *are* the data, written by one collection into one
transaction, so whatever exists is servable.
"""

from kaipanla.models import KaipanlaSectorFundFlowSnapshot


def _snapshots():
    return KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla')


def latest_trade_date():
    """The newest business date this module has any snapshot for, or ``None``."""
    return (
        _snapshots().order_by('-trade_date').values_list('trade_date', flat=True).first()
    )


def latest_snapshot(trade_date):
    """The newest slot collected on ``trade_date``, plus when its rows landed.

    Returns ``(snapshot_time, written_at)``, or ``(None, None)`` when the day has
    no rows. Both come from one query because both describe the same rows: the
    slot is *which* collection this is, ``written_at`` is *when* it was stored.

    The slot doubles as the cache identity of that day: a newly collected slot
    changes this value, which changes the cache key, so a cached payload can
    never outlive the data it was built from.

    ``written_at`` is ``created_at`` — set once, on insert. Re-collecting a slot
    (an ``INSERT ... ON CONFLICT DO UPDATE``) refreshes the values but not this
    stamp, which is the honest answer to "since when has this row existed".
    """
    row = (
        _snapshots().filter(trade_date=trade_date)
        .order_by('-snapshot_time', '-created_at')
        .values('snapshot_time', 'created_at')
        .first()
    )
    if row is None:
        return None, None
    return row['snapshot_time'], row['created_at']


def list_trade_dates():
    """Every business date with at least one snapshot, newest first."""
    return list(
        _snapshots().order_by('-trade_date').values_list('trade_date', flat=True).distinct()
    )


def list_latest_sectors(trade_date):
    """Return sectors from the last available snapshot on one date."""
    latest_time, _ = latest_snapshot(trade_date)
    if latest_time is None:
        return []
    return list(
        _snapshots().filter(trade_date=trade_date, snapshot_time=latest_time)
        .order_by('sector_name', 'sector_code')
        .values('sector_code', 'sector_name')
    )


def load_intraday_snapshot_rows(trade_date, time_axis):
    """Load the minimum fields needed to build an intraday response."""
    if not time_axis:
        return []
    return list(
        _snapshots().filter(trade_date=trade_date, snapshot_time__in=time_axis)
        .values('sector_code', 'sector_name', 'snapshot_time', 'main_net_inflow')
    )


def load_close_snapshot_rows(trade_dates, close_times):
    """Load only the exact 15:00 snapshots for a trading-day window."""
    if not trade_dates or not close_times:
        return []
    return list(
        _snapshots().filter(trade_date__in=trade_dates, snapshot_time__in=close_times)
        .order_by('-trade_date', 'sector_code')
        .values('trade_date', 'sector_code', 'sector_name', 'main_net_inflow')
    )
