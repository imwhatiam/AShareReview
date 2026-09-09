"""Pure business rules for the large-move, large-turnover stock analysis."""

from dataclasses import dataclass
from decimal import Decimal

from core.services.contracts import CompleteMarketSnapshot
from stock_moves.models import StockMoveItem


CHANGE_PERCENT_THRESHOLD = Decimal('8')
TURNOVER_THRESHOLD = Decimal('800000000')


@dataclass(frozen=True)
class StockMoveAnalysisItem:
    group: str
    rank: int
    stock_code: str
    stock_name: str
    parent_industries: tuple[dict[str, str], ...]
    change_percent: Decimal
    turnover: Decimal


@dataclass(frozen=True)
class StockMoveAnalysis:
    items: tuple[StockMoveAnalysisItem, ...]
    group_counts: dict[str, int]
    distinct_stock_count: int
    warnings: tuple[str, ...]


def build_stock_move_analysis(snapshot: CompleteMarketSnapshot) -> StockMoveAnalysis:
    """Select and rank the four SSE/SZSE large-move groups from one complete snapshot."""
    parent_industries_by_stock = _parent_industries_by_stock(snapshot)
    candidates: dict[str, list[StockMoveAnalysisItem]] = {
        choice: [] for choice in StockMoveItem.Group.values
    }
    warnings: list[str] = []
    qualifying_bse_count = 0

    for price in snapshot.prices:
        if not _has_usable_price(price):
            continue
        group = _group_for_price(price.exchange, price.change_percent, price.turnover)
        if group is None:
            if (
                price.exchange == 'bse'
                and _meets_move_and_turnover_threshold(price.change_percent, price.turnover)
            ):
                qualifying_bse_count += 1
            continue

        industries = parent_industries_by_stock.get(price.stock_code, ())
        if not price.stock_name:
            warnings.append(f'股票 {price.stock_code} 名称缺失。')
        if not industries:
            warnings.append(f'股票 {price.stock_code} 未映射到开盘啦父行业。')
        candidates[group].append(
            StockMoveAnalysisItem(
                group=group,
                rank=0,
                stock_code=price.stock_code,
                stock_name=price.stock_name,
                parent_industries=industries,
                change_percent=price.change_percent,
                turnover=price.turnover,
            )
        )

    if qualifying_bse_count:
        warnings.append(
            f'已排除 {qualifying_bse_count} 只符合阈值的北京证券交易所股票；'
            '它们不属于上证或深证四组。'
        )

    items: list[StockMoveAnalysisItem] = []
    group_counts: dict[str, int] = {}
    for group in StockMoveItem.Group.values:
        ranked = sorted(
            candidates[group],
            key=lambda item: _sort_key(group, item),
        )
        group_counts[group] = len(ranked)
        items.extend(
            StockMoveAnalysisItem(
                group=item.group,
                rank=rank,
                stock_code=item.stock_code,
                stock_name=item.stock_name,
                parent_industries=item.parent_industries,
                change_percent=item.change_percent,
                turnover=item.turnover,
            )
            for rank, item in enumerate(ranked, start=1)
        )

    return StockMoveAnalysis(
        items=tuple(items),
        group_counts=group_counts,
        distinct_stock_count=len({item.stock_code for item in items}),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _parent_industries_by_stock(snapshot: CompleteMarketSnapshot):
    result: dict[str, list[dict[str, str]]] = {}
    for industry in snapshot.parent_industries:
        label = {'code': industry.code, 'name': industry.name}
        for stock_code in industry.stock_codes:
            result.setdefault(stock_code, []).append(label)
    return {
        stock_code: tuple(sorted(labels, key=lambda label: (label['code'], label['name'])))
        for stock_code, labels in result.items()
    }


def _has_usable_price(price) -> bool:
    return (
        price.has_valid_trade
        and price.change_percent is not None
        and price.turnover is not None
    )


def _meets_move_and_turnover_threshold(change_percent: Decimal, turnover: Decimal) -> bool:
    return (
        (change_percent >= CHANGE_PERCENT_THRESHOLD or change_percent <= -CHANGE_PERCENT_THRESHOLD)
        and turnover >= TURNOVER_THRESHOLD
    )


def _group_for_price(exchange: str, change_percent: Decimal, turnover: Decimal) -> str | None:
    if turnover < TURNOVER_THRESHOLD:
        return None
    if exchange == 'sse':
        if change_percent >= CHANGE_PERCENT_THRESHOLD:
            return StockMoveItem.Group.SSE_RISE
        if change_percent <= -CHANGE_PERCENT_THRESHOLD:
            return StockMoveItem.Group.SSE_FALL
    if exchange == 'szse':
        if change_percent >= CHANGE_PERCENT_THRESHOLD:
            return StockMoveItem.Group.SZSE_RISE
        if change_percent <= -CHANGE_PERCENT_THRESHOLD:
            return StockMoveItem.Group.SZSE_FALL
    return None


def _sort_key(group: str, item: StockMoveAnalysisItem):
    if group in (StockMoveItem.Group.SSE_RISE, StockMoveItem.Group.SZSE_RISE):
        return (-item.change_percent, item.stock_code)
    return (item.change_percent, item.stock_code)
