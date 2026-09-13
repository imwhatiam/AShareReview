"""Transactional persistence for stock-move analysis results."""

from dataclasses import dataclass
from uuid import uuid4

from django.db import transaction
from django.utils import timezone

from stock_moves.models import StockMoveItem, StockMoveResult, StockMoveRun
from stock_moves.services.analysis import StockMoveAnalysis


@dataclass(frozen=True)
class StockMoveWriteResult:
    result_id: int
    record_count: int
    source_batch_id: str


def new_source_batch_id() -> str:
    return uuid4().hex


def write_stock_move_analysis(
    *,
    business_date,
    source_daily_price_version: str,
    source_industry_version: str,
    analysis: StockMoveAnalysis,
    source_batch_id: str | None = None,
) -> StockMoveWriteResult:
    """Replace the result for one source-version pair and mark its run successful.

    Both source versions are part of the identity: the stored ``industries`` came
    from the industry snapshot, so a result is only reusable while *both* inputs
    are unchanged.
    """
    batch_id = source_batch_id or new_source_batch_id()
    run = StockMoveRun.objects.using('stock_moves').create(
        source_batch_id=batch_id,
        business_date=business_date,
        status=StockMoveRun.Status.RUNNING,
        source_daily_price_version=source_daily_price_version,
        source_industry_version=source_industry_version,
    )
    try:
        with transaction.atomic(using='stock_moves'):
            result, _ = StockMoveResult.objects.using('stock_moves').update_or_create(
                business_date=business_date,
                source_daily_price_version=source_daily_price_version,
                source_industry_version=source_industry_version,
                defaults={
                    'sse_rise_count': analysis.group_counts[StockMoveItem.Group.SSE_RISE],
                    'sse_fall_count': analysis.group_counts[StockMoveItem.Group.SSE_FALL],
                    'szse_rise_count': analysis.group_counts[StockMoveItem.Group.SZSE_RISE],
                    'szse_fall_count': analysis.group_counts[StockMoveItem.Group.SZSE_FALL],
                    'bse_rise_count': analysis.group_counts[StockMoveItem.Group.BSE_RISE],
                    'bse_fall_count': analysis.group_counts[StockMoveItem.Group.BSE_FALL],
                    'distinct_stock_count': analysis.distinct_stock_count,
                    'warnings': list(analysis.warnings),
                },
            )
            StockMoveItem.objects.using('stock_moves').filter(result=result).delete()
            StockMoveItem.objects.using('stock_moves').bulk_create([
                StockMoveItem(
                    result=result,
                    group=item.group,
                    rank=item.rank,
                    stock_code=item.stock_code,
                    stock_name=item.stock_name,
                    industries=list(item.industries),
                    change_percent=item.change_percent,
                    turnover=item.turnover,
                )
                for item in analysis.items
            ])
            StockMoveRun.objects.using('stock_moves').filter(pk=run.pk).update(
                status=StockMoveRun.Status.SUCCESS,
                published_result_id=result.pk,
                total_candidate_count=analysis.distinct_stock_count,
                finished_at=timezone.now(),
            )
    except Exception as error:
        StockMoveRun.objects.using('stock_moves').filter(pk=run.pk).update(
            status=StockMoveRun.Status.FAILED,
            finished_at=timezone.now(),
            error_summary=str(error)[:1000],
        )
        raise
    return StockMoveWriteResult(result.pk, len(analysis.items), batch_id)


def record_failed_run(
    *,
    business_date,
    error: Exception,
    source_daily_price_version: str = '',
    source_industry_version: str = '',
) -> None:
    StockMoveRun.objects.using('stock_moves').create(
        source_batch_id=new_source_batch_id(),
        business_date=business_date,
        status=StockMoveRun.Status.FAILED,
        source_daily_price_version=source_daily_price_version,
        source_industry_version=source_industry_version,
        finished_at=timezone.now(),
        error_summary=str(error)[:1000],
    )
