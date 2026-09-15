"""Transactional persistence for complete Kaipanla fund-flow snapshots."""

from django.db import transaction

from kaipanla.models import KaipanlaSectorFundFlowSnapshot
from kaipanla.services.fetcher import KaipanlaSectorFundFlowFetchResult


class IncompleteKaipanlaSnapshot(ValueError):
    """Raised when a paginated upstream result must not be written."""


def write_complete_snapshot(
    *,
    fetch_result: KaipanlaSectorFundFlowFetchResult,
    snapshot_time,
) -> int:
    """Upsert one complete five-minute snapshot; return the row count written.

    **A snapshot is published the moment its rows are committed.** There is no
    second step and no second database: the module owns this table, so "written"
    and "readable" are the same event. The whole slot is one ``INSERT ... ON
    CONFLICT DO UPDATE`` inside one transaction, so a reader sees either all 104
    sectors of a slot or none of them — a half-written slot cannot be observed,
    which is what a separate publication step used to buy at the cost of a
    cross-database commit window.

    An incomplete collection raises before touching the database: partial pages
    must never be published as a full snapshot (the missing sectors would simply
    vanish from the curve, and nothing downstream could tell).
    """
    if not fetch_result.is_complete or not fetch_result.rows:
        raise IncompleteKaipanlaSnapshot(
            fetch_result.error_summary or 'Kaipanla snapshot collection was incomplete.'
        )

    snapshots = [
        KaipanlaSectorFundFlowSnapshot(
            sector_code=row.sector_code,
            sector_name=row.sector_name,
            trade_date=snapshot_time.date(),
            snapshot_time=snapshot_time,
            change_pct=row.change_pct,
            main_net_inflow=row.main_net_inflow,
            main_buy=row.main_buy,
            main_sell=row.main_sell,
            large_order_net_inflow=row.large_order_net_inflow,
            volume_ratio=row.volume_ratio,
            turnover_amount=row.turnover_amount,
            float_market_cap=row.float_market_cap,
            total_market_cap=row.total_market_cap,
        )
        for row in fetch_result.rows
    ]
    with transaction.atomic(using='kaipanla'):
        KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').bulk_create(
            snapshots,
            update_conflicts=True,
            update_fields=[
                'sector_name',
                'trade_date',
                'change_pct',
                'main_net_inflow',
                'main_buy',
                'main_sell',
                'large_order_net_inflow',
                'volume_ratio',
                'turnover_amount',
                'float_market_cap',
                'total_market_cap',
            ],
            unique_fields=['sector_code', 'snapshot_time'],
            batch_size=500,
        )
    return len(snapshots)
