"""Transactional persistence for stock-move analysis results."""

from dataclasses import dataclass
from datetime import date, datetime

from django.db import transaction
from django.utils import timezone

from stock_moves.models import StockMoveItem
from stock_moves.services.analysis import StockMoveAnalysis


@dataclass(frozen=True)
class StockMoveWriteResult:
    business_date: date
    published_at: datetime
    record_count: int


def write_stock_move_analysis(
    *,
    business_date,
    analysis: StockMoveAnalysis,
) -> StockMoveWriteResult:
    """Replace one day's rows in a single transaction.

    The transaction *is* the publication: until it commits, readers see the
    previous day's rows (or none), and after it commits they see exactly this
    result. There is no version row and no run row to keep in step, so a failed
    build leaves the previous result untouched and shows up in the command log
    instead of in a status table.

    ``published_at`` is stamped here, once per day, rather than by the field —
    a rebuild has to move it forward so the file cache stops serving the
    previous build's payload.
    """
    published_at = timezone.now()
    with transaction.atomic(using='stock_moves'):
        StockMoveItem.objects.using('stock_moves').filter(
            business_date=business_date
        ).delete()
        StockMoveItem.objects.using('stock_moves').bulk_create([
            StockMoveItem(
                business_date=business_date,
                group=item.group,
                rank=item.rank,
                stock_code=item.stock_code,
                stock_name=item.stock_name,
                industries=list(item.industries),
                change_percent=item.change_percent,
                turnover=item.turnover,
                published_at=published_at,
            )
            for item in analysis.items
        ])
    return StockMoveWriteResult(
        business_date=business_date,
        published_at=published_at,
        record_count=len(analysis.items),
    )
