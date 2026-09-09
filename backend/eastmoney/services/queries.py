"""Read-only ORM queries for independently stored Eastmoney snapshots."""

from django.db.models import Max

from eastmoney.models import EastmoneySectorFundFlowRun, EastmoneySectorFundFlowSnapshot


def latest_snapshot_trade_date():
    """Return the latest business date with an available Eastmoney snapshot."""
    return EastmoneySectorFundFlowSnapshot.objects.using('eastmoney').aggregate(
        latest_date=Max('trade_date')
    )['latest_date']


def list_latest_sectors(trade_date):
    """Return sectors from the last available snapshot on one business date."""
    latest_time = EastmoneySectorFundFlowSnapshot.objects.using('eastmoney').filter(
        trade_date=trade_date
    ).aggregate(latest_time=Max('snapshot_time'))['latest_time']
    if latest_time is None:
        return []
    return list(
        EastmoneySectorFundFlowSnapshot.objects.using('eastmoney').filter(
            trade_date=trade_date,
            snapshot_time=latest_time,
        ).order_by('sector_name', 'sector_code').values('sector_code', 'sector_name')
    )


def load_intraday_snapshot_rows(trade_date, time_axis):
    """Load the minimum fields needed to build an intraday response."""
    return list(
        EastmoneySectorFundFlowSnapshot.objects.using('eastmoney').filter(
            trade_date=trade_date,
            snapshot_time__in=time_axis,
        ).values(
            'sector_code',
            'sector_name',
            'snapshot_time',
            'main_net_inflow',
            'source_batch_id',
        )
    )


def load_close_snapshot_rows(trade_dates, close_times):
    """Load only exact 15:00 snapshots for a trading-day window."""
    if not trade_dates:
        return []
    return list(
        EastmoneySectorFundFlowSnapshot.objects.using('eastmoney').filter(
            trade_date__in=trade_dates,
            snapshot_time__in=close_times,
        ).order_by('-trade_date', 'sector_code').values(
            'trade_date',
            'sector_code',
            'sector_name',
            'main_net_inflow',
            'source_batch_id',
        )
    )


def query_completeness(source_batch_ids):
    """Describe whether source runs omitted either independently fetched ranking."""
    batch_ids = {batch_id for batch_id in source_batch_ids if batch_id}
    if not batch_ids:
        return {'completeness': 'complete', 'missing_directions': []}

    runs = EastmoneySectorFundFlowRun.objects.using('eastmoney').filter(
        source_batch_id__in=batch_ids
    )
    missing_directions = set()
    for run in runs:
        if run.status != EastmoneySectorFundFlowRun.Status.PARTIAL:
            continue
        if run.inflow_status != EastmoneySectorFundFlowRun.DirectionStatus.COMPLETE:
            missing_directions.add('inflow')
        if run.outflow_status != EastmoneySectorFundFlowRun.DirectionStatus.COMPLETE:
            missing_directions.add('outflow')

    return {
        'completeness': 'partial' if missing_directions else 'complete',
        'missing_directions': sorted(missing_directions),
    }


def latest_snapshot_completeness(trade_date):
    """Return direction completeness for the most recent snapshot on a date."""
    latest_time = EastmoneySectorFundFlowSnapshot.objects.using('eastmoney').filter(
        trade_date=trade_date
    ).aggregate(latest_time=Max('snapshot_time'))['latest_time']
    if latest_time is None:
        return {'completeness': 'complete', 'missing_directions': []}
    source_batch_ids = EastmoneySectorFundFlowSnapshot.objects.using('eastmoney').filter(
        trade_date=trade_date,
        snapshot_time=latest_time,
    ).values_list('source_batch_id', flat=True)
    return query_completeness(source_batch_ids)
