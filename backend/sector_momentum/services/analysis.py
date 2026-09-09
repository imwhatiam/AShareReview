"""Pure calculations for the parent-industry momentum rankings."""

from dataclasses import dataclass
from decimal import Decimal

from core.services.contracts import CompleteMarketSnapshot, MarketPrice

ABOVE_5PCT = 'above_5pct'
TOP_5_PERCENT = 'top_5_percent'
_METRICS = (ABOVE_5PCT, TOP_5_PERCENT)
_FIVE_PERCENT = Decimal('5')
_TOP_PERCENT = Decimal('0.05')
_MAX_RANKINGS = 10


@dataclass(frozen=True)
class MomentumStock:
    stock_code: str
    stock_name: str
    change_percent: Decimal
    turnover: Decimal


@dataclass(frozen=True)
class MomentumRanking:
    metric: str
    rank: int
    industry_code: str
    industry_name: str
    stock_count: int
    average_change_percent: Decimal
    industry_turnover: Decimal
    market_turnover_ratio: Decimal
    score: Decimal
    stocks: tuple[MomentumStock, ...]


@dataclass(frozen=True)
class SectorMomentumAnalysis:
    source_daily_price_version: str
    source_industry_version: str
    total_market_turnover: Decimal
    unmapped_stock_count: int
    top_5_percent_sample_size: int
    rankings_by_metric: dict[str, tuple[MomentumRanking, ...]]


def _is_valid_price(price: MarketPrice) -> bool:
    return (
        price.has_valid_trade
        and price.change_percent is not None
        and price.turnover is not None
    )


def _parent_industries_by_stock(snapshot: CompleteMarketSnapshot) -> dict[str, tuple[tuple[str, str], ...]]:
    memberships: dict[str, list[tuple[str, str]]] = {}
    for industry in snapshot.parent_industries:
        for stock_code in industry.stock_codes:
            memberships.setdefault(stock_code, []).append((industry.code, industry.name))
    return {
        stock_code: tuple(sorted(values, key=lambda item: item[0]))
        for stock_code, values in memberships.items()
    }


def _build_rankings(
    metric: str,
    selected_prices: tuple[MarketPrice, ...],
    memberships: dict[str, tuple[tuple[str, str], ...]],
    total_market_turnover: Decimal,
) -> tuple[MomentumRanking, ...]:
    grouped: dict[tuple[str, str], list[MarketPrice]] = {}
    for price in selected_prices:
        for industry in memberships.get(price.stock_code, ()):
            grouped.setdefault(industry, []).append(price)

    rankings: list[MomentumRanking] = []
    for (industry_code, industry_name), prices in grouped.items():
        stocks = tuple(
            MomentumStock(
                stock_code=price.stock_code,
                stock_name=price.stock_name,
                change_percent=price.change_percent,
                turnover=price.turnover,
            )
            for price in sorted(prices, key=lambda value: (-value.change_percent, value.stock_code))
        )
        stock_count = len(stocks)
        industry_turnover = sum((stock.turnover for stock in stocks), Decimal('0'))
        average_change_percent = sum(
            (stock.change_percent for stock in stocks), Decimal('0')
        ) / stock_count
        market_turnover_ratio = (
            industry_turnover / total_market_turnover
            if total_market_turnover else Decimal('0')
        )
        score = stock_count * average_change_percent * market_turnover_ratio
        rankings.append(
            MomentumRanking(
                metric=metric,
                rank=0,
                industry_code=industry_code,
                industry_name=industry_name,
                stock_count=stock_count,
                average_change_percent=average_change_percent,
                industry_turnover=industry_turnover,
                market_turnover_ratio=market_turnover_ratio,
                score=score,
                stocks=stocks,
            )
        )

    sorted_rankings = sorted(
        rankings,
        key=lambda value: (-value.score, value.industry_code),
    )[:_MAX_RANKINGS]
    return tuple(
        MomentumRanking(**{**ranking.__dict__, 'rank': index})
        for index, ranking in enumerate(sorted_rankings, start=1)
    )


def build_sector_momentum_analysis(
    snapshot: CompleteMarketSnapshot, source_industry_version: str
) -> SectorMomentumAnalysis:
    """Build both metrics from one complete local market-data snapshot."""
    valid_prices = tuple(price for price in snapshot.prices if _is_valid_price(price))
    total_market_turnover = sum((price.turnover for price in valid_prices), Decimal('0'))
    memberships = _parent_industries_by_stock(snapshot)
    unmapped_stock_count = sum(
        1 for price in valid_prices if price.stock_code not in memberships
    )
    above_five = tuple(
        price for price in valid_prices if price.change_percent > _FIVE_PERCENT
    )
    top_sample_size = max(1, int(len(valid_prices) * _TOP_PERCENT)) if valid_prices else 0
    top_five = tuple(sorted(
        valid_prices, key=lambda value: (-value.change_percent, value.stock_code)
    )[:top_sample_size])

    return SectorMomentumAnalysis(
        source_daily_price_version=snapshot.data_version.version,
        source_industry_version=source_industry_version,
        total_market_turnover=total_market_turnover,
        unmapped_stock_count=unmapped_stock_count,
        top_5_percent_sample_size=top_sample_size,
        rankings_by_metric={
            ABOVE_5PCT: _build_rankings(
                ABOVE_5PCT, above_five, memberships, total_market_turnover
            ),
            TOP_5_PERCENT: _build_rankings(
                TOP_5_PERCENT, top_five, memberships, total_market_turnover
            ),
        },
    )
