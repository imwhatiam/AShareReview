"""Transactional persistence for sector-momentum analysis results."""

from dataclasses import dataclass
from uuid import uuid4

from django.db import transaction
from django.utils import timezone

from sector_momentum.models import (
    SectorMomentumRanking,
    SectorMomentumResult,
    SectorMomentumRun,
)
from sector_momentum.services.analysis import SectorMomentumAnalysis


@dataclass(frozen=True)
class SectorMomentumWriteResult:
    result_id: int
    record_count: int
    source_batch_id: str


def new_source_batch_id() -> str:
    return uuid4().hex


def _serialize_stocks(stocks) -> list[dict]:
    return [
        {
            'code': stock.stock_code,
            'name': stock.stock_name,
            'change_percent': str(stock.change_percent),
            'turnover': str(stock.turnover),
        }
        for stock in stocks
    ]


def write_sector_momentum_analysis(
    *,
    business_date,
    analysis: SectorMomentumAnalysis,
    source_batch_id: str | None = None,
) -> SectorMomentumWriteResult:
    """Replace the output for one pair of immutable public source versions."""
    batch_id = source_batch_id or new_source_batch_id()
    run = SectorMomentumRun.objects.using('sector_momentum').create(
        source_batch_id=batch_id,
        business_date=business_date,
        status=SectorMomentumRun.Status.RUNNING,
        source_daily_price_version=analysis.source_daily_price_version,
        source_industry_version=analysis.source_industry_version,
    )
    try:
        with transaction.atomic(using='sector_momentum'):
            result, _ = SectorMomentumResult.objects.using('sector_momentum').update_or_create(
                business_date=business_date,
                source_daily_price_version=analysis.source_daily_price_version,
                source_industry_version=analysis.source_industry_version,
                defaults={
                    'total_market_turnover': analysis.total_market_turnover,
                    'unmapped_stock_count': analysis.unmapped_stock_count,
                },
            )
            SectorMomentumRanking.objects.using('sector_momentum').filter(result=result).delete()
            rankings = [
                ranking
                for values in analysis.rankings_by_metric.values()
                for ranking in values
            ]
            SectorMomentumRanking.objects.using('sector_momentum').bulk_create([
                SectorMomentumRanking(
                    result=result,
                    metric=ranking.metric,
                    rank=ranking.rank,
                    industry_code=ranking.industry_code,
                    industry_name=ranking.industry_name,
                    stock_count=ranking.stock_count,
                    average_change_percent=ranking.average_change_percent,
                    industry_turnover=ranking.industry_turnover,
                    market_turnover_ratio=ranking.market_turnover_ratio,
                    score=ranking.score,
                    stocks=_serialize_stocks(ranking.stocks),
                )
                for ranking in rankings
            ])
            SectorMomentumRun.objects.using('sector_momentum').filter(pk=run.pk).update(
                status=SectorMomentumRun.Status.SUCCESS,
                published_result_id=result.pk,
                total_market_turnover=analysis.total_market_turnover,
                unmapped_stock_count=analysis.unmapped_stock_count,
                finished_at=timezone.now(),
            )
    except Exception as error:
        SectorMomentumRun.objects.using('sector_momentum').filter(pk=run.pk).update(
            status=SectorMomentumRun.Status.FAILED,
            finished_at=timezone.now(),
            error_summary=str(error)[:1000],
        )
        raise
    return SectorMomentumWriteResult(result.pk, len(rankings), batch_id)


def record_failed_run(
    *,
    business_date,
    error: Exception,
    source_daily_price_version: str = '',
    source_industry_version: str = '',
) -> None:
    SectorMomentumRun.objects.using('sector_momentum').create(
        source_batch_id=new_source_batch_id(),
        business_date=business_date,
        status=SectorMomentumRun.Status.FAILED,
        source_daily_price_version=source_daily_price_version,
        source_industry_version=source_industry_version,
        finished_at=timezone.now(),
        error_summary=str(error)[:1000],
    )
