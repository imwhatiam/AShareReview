"""Read-only ORM queries for the independently stored Kaipanla snapshots."""

from django.db.models import Max

from kaipanla.models import KaipanlaSectorFundFlowSnapshot


def latest_snapshot_trade_date():
    """Return the latest business date with an available Kaipanla snapshot."""
    return KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').aggregate(
        latest_date=Max('trade_date')
    )['latest_date']


def list_latest_sectors(trade_date):
    """Return sectors from the last available snapshot on one business date."""
    latest_time = KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').filter(
        trade_date=trade_date
    ).aggregate(latest_time=Max('snapshot_time'))['latest_time']
    if latest_time is None:
        return []
    return list(
        KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').filter(
            trade_date=trade_date,
            snapshot_time=latest_time,
        ).order_by('sector_name', 'sector_code').values('sector_code', 'sector_name')
    )


def load_intraday_snapshot_rows(trade_date, time_axis):
    """Load the minimum fields needed to build an intraday response."""
    return list(
        KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').filter(
            trade_date=trade_date,
            snapshot_time__in=time_axis,
        ).values('sector_code', 'sector_name', 'snapshot_time', 'main_net_inflow')
    )


def load_close_snapshot_rows(trade_dates, close_times):
    """Load only the exact 15:00 snapshots for a trading-day window."""
    if not trade_dates:
        return []
    return list(
        KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').filter(
            trade_date__in=trade_dates,
            snapshot_time__in=close_times,
        ).order_by('-trade_date', 'sector_code').values(
            'trade_date', 'sector_code', 'sector_name', 'main_net_inflow'
        )
    )
