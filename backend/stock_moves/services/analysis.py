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
    industries: tuple[dict[str, str], ...]
    change_percent: Decimal
    turnover: Decimal


@dataclass(frozen=True)
class StockMoveAnalysis:
    items: tuple[StockMoveAnalysisItem, ...]
    group_counts: dict[str, int]
    distinct_stock_count: int
    warnings: tuple[str, ...]


def build_stock_move_analysis(snapshot: CompleteMarketSnapshot) -> StockMoveAnalysis:
    """Select and rank the SSE/SZSE/BSE large-move groups.

    The six ``*_rise``/``*_fall`` groups answer "which stocks moved a lot on
    heavy volume, per market and per direction". Beijing Stock Exchange stocks
    meet the same two thresholds but belong to neither of the two main
    exchanges, so they get their own pair of groups instead of only being
    reported as a dropped count.
    """
    industries_by_stock = _industries_by_stock(snapshot)
    candidates: dict[str, list[StockMoveAnalysisItem]] = {
        choice: [] for choice in StockMoveItem.Group.values
    }
    warnings: list[str] = []

    for price in snapshot.prices:
        if not _has_usable_price(price):
            continue
        group = _group_for_price(price.exchange, price.change_percent, price.turnover)
        if group is None:
            continue

        industries = industries_by_stock.get(price.stock_code, ())
        if not price.stock_name:
            warnings.append(f'股票 {price.stock_code} 名称缺失。')
        if not industries:
            warnings.append(f'股票 {price.stock_code} 未映射到开盘啦板块。')
        candidates[group].append(
            StockMoveAnalysisItem(
                group=group,
                rank=0,
                stock_code=price.stock_code,
                stock_name=price.stock_name,
                industries=industries,
                change_percent=price.change_percent,
                turnover=price.turnover,
            )
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
                industries=item.industries,
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


def _industries_by_stock(snapshot: CompleteMarketSnapshot):
    result: dict[str, list[dict[str, str]]] = {}
    for industry in snapshot.industries:
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


def _group_for_price(exchange: str, change_percent: Decimal, turnover: Decimal) -> str | None:
    if turnover < TURNOVER_THRESHOLD:
        return None
    if abs(change_percent) < CHANGE_PERCENT_THRESHOLD:
        return None
    if exchange == 'sse':
        return (
            StockMoveItem.Group.SSE_RISE
            if change_percent > 0
            else StockMoveItem.Group.SSE_FALL
        )
    if exchange == 'szse':
        return (
            StockMoveItem.Group.SZSE_RISE
            if change_percent > 0
            else StockMoveItem.Group.SZSE_FALL
        )
    if exchange == 'bse':
        # 北交所和沪深一样按方向拆组：页面是"行=市场、列=涨跌"的看板，
        # 混成一组就没法落进"北交所上涨 / 北交所下跌"这两栏。
        return (
            StockMoveItem.Group.BSE_RISE
            if change_percent > 0
            else StockMoveItem.Group.BSE_FALL
        )
    return None


def _sort_key(group: str, item: StockMoveAnalysisItem):
    # 上涨组按涨幅降序、下跌组按涨幅升序，让每组最有代表性的股票先出现。
    if group in (
        StockMoveItem.Group.SSE_RISE,
        StockMoveItem.Group.SZSE_RISE,
        StockMoveItem.Group.BSE_RISE,
    ):
        return (-item.change_percent, item.stock_code)
    return (item.change_percent, item.stock_code)
