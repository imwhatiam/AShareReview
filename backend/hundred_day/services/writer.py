"""Transactional persistence for hundred-day analysis results."""

from dataclasses import dataclass
from uuid import uuid4

from django.db import transaction
from django.utils import timezone

from hundred_day.models import (
    HundredDayIndustrySummary,
    HundredDayResult,
    HundredDayRun,
    HundredDayStockFlag,
    HundredDayTrend,
)
from hundred_day.services.analysis import HundredDayAnalysis


@dataclass(frozen=True)
class HundredDayWriteResult:
    result_id: int
    record_count: int
    source_batch_id: str


def new_source_batch_id() -> str:
    return uuid4().hex


def _serialize_stocks(stocks) -> list[dict]:
    """把明细转成 JSON 可存的形式；Decimal 必须先转字符串，JSONField 存不了 Decimal。"""
    return [
        {
            'code': stock.stock_code,
            'name': stock.stock_name,
            'change_percent': None if stock.change_percent is None else str(stock.change_percent),
            'turnover': None if stock.turnover is None else str(stock.turnover),
        }
        for stock in stocks
    ]


def write_hundred_day_analysis(
    *, analysis: HundredDayAnalysis, source_batch_id: str | None = None
) -> HundredDayWriteResult:
    """Atomically replace one source-version result and mark its run successful."""
    batch_id = source_batch_id or new_source_batch_id()
    run = HundredDayRun.objects.using('hundred_day').create(
        source_batch_id=batch_id,
        business_date=analysis.business_date,
        status=HundredDayRun.Status.RUNNING,
        source_daily_price_version=analysis.source_daily_price_version,
        source_industry_version=analysis.source_industry_version,
    )
    try:
        with transaction.atomic(using='hundred_day'):
            result, _ = HundredDayResult.objects.using('hundred_day').update_or_create(
                business_date=analysis.business_date,
                source_daily_price_version=analysis.source_daily_price_version,
                source_industry_version=analysis.source_industry_version,
                defaults={
                    'valid_stock_count': analysis.valid_stock_count,
                    'new_high_count': analysis.new_high_count,
                    'new_low_count': analysis.new_low_count,
                },
            )
            HundredDayStockFlag.objects.using('hundred_day').filter(result=result).delete()
            HundredDayIndustrySummary.objects.using('hundred_day').filter(result=result).delete()
            HundredDayTrend.objects.using('hundred_day').filter(result=result).delete()
            HundredDayStockFlag.objects.using('hundred_day').bulk_create([
                HundredDayStockFlag(
                    result=result,
                    stock_code=flag.stock_code,
                    stock_name=flag.stock_name,
                    industries=list(flag.industries),
                    is_new_high=flag.is_new_high,
                    is_new_low=flag.is_new_low,
                )
                for flag in analysis.stock_flags
            ])
            HundredDayIndustrySummary.objects.using('hundred_day').bulk_create([
                HundredDayIndustrySummary(
                    result=result,
                    industry_code=summary.industry_code,
                    industry_name=summary.industry_name,
                    stock_count=summary.stock_count,
                    new_high_count=summary.new_high_count,
                    new_low_count=summary.new_low_count,
                    new_high_stocks=_serialize_stocks(summary.new_high_stocks),
                    new_low_stocks=_serialize_stocks(summary.new_low_stocks),
                )
                for summary in analysis.industry_summaries
            ])
            HundredDayTrend.objects.using('hundred_day').bulk_create([
                HundredDayTrend(
                    result=result,
                    trade_date=point.trade_date,
                    valid_stock_count=point.valid_stock_count,
                    new_high_count=point.new_high_count,
                    new_low_count=point.new_low_count,
                    new_high_ratio=point.new_high_ratio,
                    new_low_ratio=point.new_low_ratio,
                )
                for point in analysis.trend_points
            ])
            HundredDayRun.objects.using('hundred_day').filter(pk=run.pk).update(
                status=HundredDayRun.Status.SUCCESS,
                published_result_id=result.pk,
                valid_stock_count=analysis.valid_stock_count,
                finished_at=timezone.now(),
            )
    except Exception as error:
        HundredDayRun.objects.using('hundred_day').filter(pk=run.pk).update(
            status=HundredDayRun.Status.FAILED,
            finished_at=timezone.now(),
            error_summary=str(error)[:1000],
        )
        raise
    return HundredDayWriteResult(result.pk, len(analysis.stock_flags), batch_id)


def record_failed_run(
    *,
    business_date,
    error: Exception,
    source_daily_price_version: str = '',
    source_industry_version: str = '',
) -> None:
    HundredDayRun.objects.using('hundred_day').create(
        source_batch_id=new_source_batch_id(),
        business_date=business_date,
        status=HundredDayRun.Status.FAILED,
        source_daily_price_version=source_daily_price_version,
        source_industry_version=source_industry_version,
        finished_at=timezone.now(),
        error_summary=str(error)[:1000],
    )
