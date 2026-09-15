"""Transactional persistence for sector-momentum analysis results."""

from dataclasses import dataclass
from datetime import date, datetime

from django.db import transaction
from django.utils import timezone

from sector_momentum.models import SectorMomentumRanking
from sector_momentum.services.analysis import SectorMomentumAnalysis


@dataclass(frozen=True)
class SectorMomentumWriteResult:
    business_date: date
    published_at: datetime
    record_count: int


def _serialize_stocks(stocks) -> list[dict]:
    """The ranking's stock detail — the single source every derived number reads.

    ``change_percent`` / ``turnover`` are stored as strings so they round-trip
    exactly: the read path turns them back into ``Decimal`` and recomputes the
    industry's count, average, turnover, ratio and score from them.
    """
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
) -> SectorMomentumWriteResult:
    """Replace one day's rankings in a single transaction.

    The transaction *is* the publication: the day's rankings appear together, or
    not at all. A failed build therefore leaves the previous result in place and
    is reported by the command log rather than by a status table.

    ``published_at`` is stamped here, once per day, rather than by the field —
    a rebuild has to move it forward so the file cache stops serving the
    previous build's payload.
    """
    published_at = timezone.now()
    with transaction.atomic(using='sector_momentum'):
        SectorMomentumRanking.objects.using('sector_momentum').filter(
            business_date=business_date
        ).delete()
        rankings = [
            ranking
            for values in analysis.rankings_by_metric.values()
            for ranking in values
        ]
        SectorMomentumRanking.objects.using('sector_momentum').bulk_create([
            SectorMomentumRanking(
                business_date=business_date,
                metric=ranking.metric,
                industry_code=ranking.industry_code,
                industry_name=ranking.industry_name,
                stocks=_serialize_stocks(ranking.stocks),
                total_market_turnover=analysis.total_market_turnover,
                unmapped_stock_count=analysis.unmapped_stock_count,
                published_at=published_at,
            )
            for ranking in rankings
        ])
    return SectorMomentumWriteResult(
        business_date=business_date,
        published_at=published_at,
        record_count=len(rankings),
    )
