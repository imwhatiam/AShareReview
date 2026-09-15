"""Transactional persistence for hundred-day analysis results."""

from dataclasses import dataclass
from datetime import date, datetime

from django.db import transaction
from django.utils import timezone

from hundred_day.models import (
    HundredDayBreadth,
    HundredDayIndustrySummary,
    HundredDayStockFlag,
)
from hundred_day.services.analysis import HundredDayAnalysis


@dataclass(frozen=True)
class HundredDayWriteResult:
    business_date: date
    published_at: datetime
    record_count: int


def write_hundred_day_analysis(*, analysis: HundredDayAnalysis) -> HundredDayWriteResult:
    """Replace one business date's rows across the module's three tables.

    The transaction *is* the publication: the breadth points, the stock flags and
    the industry summaries all appear together, or not at all. A failed build
    leaves the previous result in place and is reported by the command log rather
    than by a status table.

    市场宽度写的是这次分析窗口里的每一个交易日（不只是业务日期那一个），页面的
    趋势图直接读它们；业务日期那一行同时就是"当日结果"，所以不再单独写一份当日
    汇总。``published_at`` 在这里按发布统一取一次 —— 重跑必须让它前进，否则文件
    缓存会在 TTL 内继续发上一版报文。
    """
    business_date = analysis.business_date
    published_at = timezone.now()
    with transaction.atomic(using='hundred_day'):
        for model in (
            HundredDayBreadth,
            HundredDayStockFlag,
            HundredDayIndustrySummary,
        ):
            model.objects.using('hundred_day').filter(
                business_date=business_date
            ).delete()
        HundredDayBreadth.objects.using('hundred_day').bulk_create([
            HundredDayBreadth(
                business_date=business_date,
                trade_date=point.trade_date,
                valid_stock_count=point.valid_stock_count,
                new_high_count=point.new_high_count,
                new_low_count=point.new_low_count,
                published_at=published_at,
            )
            for point in analysis.trend_points
        ])
        HundredDayStockFlag.objects.using('hundred_day').bulk_create([
            HundredDayStockFlag(
                business_date=business_date,
                stock_code=flag.stock_code,
                stock_name=flag.stock_name,
                industries=list(flag.industries),
                is_new_high=flag.is_new_high,
                is_new_low=flag.is_new_low,
                change_percent=flag.change_percent,
                turnover=flag.turnover,
            )
            for flag in analysis.stock_flags
        ])
        HundredDayIndustrySummary.objects.using('hundred_day').bulk_create([
            HundredDayIndustrySummary(
                business_date=business_date,
                industry_code=summary.industry_code,
                industry_name=summary.industry_name,
                stock_count=summary.stock_count,
            )
            for summary in analysis.industry_summaries
        ])
    return HundredDayWriteResult(
        business_date=business_date,
        published_at=published_at,
        record_count=len(analysis.stock_flags),
    )
