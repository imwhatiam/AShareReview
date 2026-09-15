"""Pure analysis for the 百日新高新低占比 module."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Mapping

from core.services.contracts import Industry
from hundred_day.services.flags import HighLowFlag, HighLowFlagResult, compute_high_low_flags

MAX_INPUT_TRADING_DAY_POSITIONS = 199
MAX_TREND_POINTS = 100


class InsufficientHundredDayHistory(ValueError):
    """Raised instead of publishing a fabricated zero-valued analysis."""


@dataclass(frozen=True)
class TargetDayQuote:
    """目标交易日的行情，用于板块明细里展示涨幅与成交额。"""

    change_percent: Decimal | None
    turnover: Decimal | None


@dataclass(frozen=True)
class HistoricalCloseData:
    """The bounded local public-data input needed for hundred-day analysis."""

    business_date: date
    trading_days: tuple[date, ...]
    close_prices_by_stock: Mapping[str, Mapping[date, Decimal | None]]
    stock_names_by_code: Mapping[str, str]
    industries: tuple[Industry, ...]
    # 只覆盖目标交易日：明细里要展示当日的涨幅与成交额，历史日不需要。
    target_day_quotes: Mapping[str, TargetDayQuote]


@dataclass(frozen=True)
class HundredDayStockAnalysis:
    stock_code: str
    stock_name: str
    industries: tuple[dict[str, str], ...]
    is_new_high: bool
    is_new_low: bool
    change_percent: Decimal | None
    turnover: Decimal | None


@dataclass(frozen=True)
class HundredDayIndustryAnalysis:
    """One parent industry's aggregates.

    只有 ``stock_count`` 落库 —— 它含未被标记的成分股，推不出来。新高低计数是
    ``HundredDayStockFlag`` 的函数，读路径按 ``industries`` 分组现算（见
    ``services/read_path.py``）；写入时不再算第二遍，那样只会多一份可能与读结果
    不一致的副本。
    """

    industry_code: str
    industry_name: str
    stock_count: int


@dataclass(frozen=True)
class HundredDayTrendAnalysis:
    """One point of the trend chart, i.e. one row of the market-breadth table.

    只带落库的三个计数：两个占比是它们与 ``valid_stock_count`` 的商，读路径序列化时
    现算并按 ``_TREND_RATIO_PLACES`` 收尾（``read_path._ratio_text``）。
    """

    trade_date: date
    valid_stock_count: int
    new_high_count: int
    new_low_count: int


@dataclass(frozen=True)
class HundredDayAnalysis:
    """One business date's hundred-day result.

    ``trend_points`` 覆盖分析窗口里的每一个交易日，其中 ``trade_date`` 等于
    ``business_date`` 的那一点**就是当日结果**：写进市场宽度表之后，业务日期那一行
    同时扮演"当日"与"趋势最后一个点"，读路径从那一行取当日数字（见
    ``read_path._serialize``）。所以这里不再单独挂一份当日汇总。
    """

    business_date: date
    stock_flags: tuple[HundredDayStockAnalysis, ...]
    industry_summaries: tuple[HundredDayIndustryAnalysis, ...]
    trend_points: tuple[HundredDayTrendAnalysis, ...]


def _industries_by_stock(
    industries: tuple[Industry, ...],
) -> dict[str, tuple[dict[str, str], ...]]:
    memberships: dict[str, list[dict[str, str]]] = {}
    for industry in industries:
        membership = {'code': industry.code, 'name': industry.name}
        for stock_code in industry.stock_codes:
            memberships.setdefault(stock_code, []).append(membership)
    return {
        stock_code: tuple(
            {'code': code, 'name': name}
            for code, name in sorted(
                {(item['code'], item['name']) for item in values}, key=lambda item: item[0]
            )
        )
        for stock_code, values in memberships.items()
    }


def _stock_analysis(
    flags: tuple[HighLowFlag, ...],
    source: HistoricalCloseData,
    memberships: Mapping[str, tuple[dict[str, str], ...]],
) -> tuple[HundredDayStockAnalysis, ...]:
    """Attach the target-day quote to every flag.

    行情就在这里落到个股标志上，行业维度的明细名单不再单独存一份：一只股票属于
    多个行业时，它会在每个行业的名单里出现，但涨幅与成交额只在这里写一次。
    """
    analyses = []
    for flag in flags:
        quote = source.target_day_quotes.get(flag.stock_code)
        analyses.append(
            HundredDayStockAnalysis(
                stock_code=flag.stock_code,
                stock_name=source.stock_names_by_code.get(flag.stock_code, flag.stock_code),
                industries=memberships.get(flag.stock_code, ()),
                is_new_high=flag.is_new_high,
                is_new_low=flag.is_new_low,
                change_percent=None if quote is None else quote.change_percent,
                turnover=None if quote is None else quote.turnover,
            )
        )
    return tuple(analyses)


def _industry_summaries(
    *,
    valid_stock_codes: set[str],
    industries: tuple[Industry, ...],
) -> tuple[HundredDayIndustryAnalysis, ...]:
    """Count each industry's valid constituents; the stock lists are rebuilt on read."""
    summaries: list[HundredDayIndustryAnalysis] = []
    for industry in sorted(industries, key=lambda item: item.code):
        # 只取"有效成分股数"：先排序再取长度是白做的功。
        stock_count = len(set(industry.stock_codes) & valid_stock_codes)
        # 名单是从 stock_codes 里筛出来的，所以「有名单」必然「有成分股」：判空只需看计数。
        if not stock_count:
            continue
        summaries.append(
            HundredDayIndustryAnalysis(
                industry_code=industry.code,
                industry_name=industry.name,
                stock_count=stock_count,
            )
        )
    return tuple(summaries)


def _trend_points(flag_result: HighLowFlagResult) -> tuple[HundredDayTrendAnalysis, ...]:
    trend_days = tuple(flag_result.flags_by_date)[-MAX_TREND_POINTS:]
    points = []
    for trade_date in trend_days:
        flags = flag_result.flags_by_date[trade_date]
        points.append(
            HundredDayTrendAnalysis(
                trade_date=trade_date,
                valid_stock_count=flag_result.valid_stock_counts_by_date[trade_date],
                new_high_count=sum(flag.is_new_high for flag in flags),
                new_low_count=sum(flag.is_new_low for flag in flags),
            )
        )
    return tuple(points)


def build_hundred_day_analysis(source: HistoricalCloseData) -> HundredDayAnalysis:
    """Build target-day stock and parent-industry results plus a bounded trend."""
    if not source.trading_days or source.trading_days[-1] != source.business_date:
        raise ValueError('The source business date must match the final trading-day position.')
    if len(source.trading_days) > MAX_INPUT_TRADING_DAY_POSITIONS:
        raise ValueError(
            f'Hundred-day analysis accepts at most {MAX_INPUT_TRADING_DAY_POSITIONS} positions.'
        )

    flag_result = compute_high_low_flags(source.trading_days, source.close_prices_by_stock)
    if not flag_result.has_sufficient_history:
        raise InsufficientHundredDayHistory(
            'Hundred-day analysis requires at least '
            f'{flag_result.required_trading_day_positions} trading-day positions; '
            f'only {flag_result.available_trading_day_positions} are available.'
        )

    business_date = source.business_date
    target_flags = flag_result.flags_by_date[business_date]
    memberships = _industries_by_stock(source.industries)
    stock_flags = _stock_analysis(target_flags, source, memberships)
    valid_stock_codes = {
        stock_code
        for stock_code, closes in source.close_prices_by_stock.items()
        if closes.get(business_date) is not None
    }
    trend_points = _trend_points(flag_result)
    return HundredDayAnalysis(
        business_date=business_date,
        stock_flags=stock_flags,
        industry_summaries=_industry_summaries(
            valid_stock_codes=valid_stock_codes,
            industries=source.industries,
        ),
        trend_points=trend_points,
    )
