"""Read-only ORM queries for the independently stored Kaipanla snapshots."""

from django.db.models import Max

from core.models import DataVersion
from kaipanla.models import KaipanlaSectorFundFlowSnapshot

DATASET_KEY = 'kaipanla_sector_fund_flow'


def published_version_strings(trade_dates) -> set[str]:
    """The snapshot versions that are *published* on those trading days.

    Every row query filters on this set. The write path commits the rows and the
    ``DataVersion`` in two different databases, so a crash in between leaves rows
    that are readable but not published; filtering by version keeps them out of
    every answer instead of handing them out under the previous version's name
    (and caching them under its key). Pre-existing rows are stamped by migration
    ``0002``.
    """
    days = [day for day in trade_dates if day is not None]
    if not days:
        return set()
    return set(
        DataVersion.objects.filter(
            dataset_key=DATASET_KEY,
            status=DataVersion.Status.COMPLETE,
            business_date__in=days,
        ).values_list('version', flat=True)
    )


def list_latest_sectors(trade_date, versions):
    """Return sectors from the last available published snapshot on one date."""
    if not versions:
        return []
    latest_time = KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').filter(
        trade_date=trade_date,
        source_data_version__in=versions,
    ).aggregate(latest_time=Max('snapshot_time'))['latest_time']
    if latest_time is None:
        return []
    return list(
        KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').filter(
            trade_date=trade_date,
            snapshot_time=latest_time,
            source_data_version__in=versions,
        ).order_by('sector_name', 'sector_code').values('sector_code', 'sector_name')
    )


def load_intraday_snapshot_rows(trade_date, time_axis, versions):
    """Load the minimum fields needed to build an intraday response."""
    if not versions:
        return []
    return list(
        KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').filter(
            trade_date=trade_date,
            snapshot_time__in=time_axis,
            source_data_version__in=versions,
        ).values('sector_code', 'sector_name', 'snapshot_time', 'main_net_inflow')
    )


def load_close_snapshot_rows(trade_dates, close_times, versions):
    """Load only the exact 15:00 snapshots for a trading-day window."""
    if not trade_dates or not versions:
        return []
    return list(
        KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').filter(
            trade_date__in=trade_dates,
            snapshot_time__in=close_times,
            source_data_version__in=versions,
        ).order_by('-trade_date', 'sector_code').values(
            'trade_date', 'sector_code', 'sector_name', 'main_net_inflow'
        )
    )
