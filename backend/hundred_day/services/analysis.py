"""Pure analysis for the 百日新高新低占比 module."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Mapping

from core.services.contracts import MarketDataVersion, ParentIndustry
from hundred_day.services.flags import HighLowFlag, HighLowFlagResult, compute_high_low_flags

MAX_INPUT_TRADING_DAY_POSITIONS = 199
MAX_TREND_POINTS = 100


class InsufficientHundredDayHistory(ValueError):
    """Raised instead of publishing a fabricated zero-valued analysis."""


@dataclass(frozen=True)
class HistoricalCloseData:
    """The bounded local public-data input needed for hundred-day analysis."""

    data_version: MarketDataVersion
    trading_days: tuple[date, ...]
    close_prices_by_stock: Mapping[str, Mapping[date, Decimal | None]]
    stock_names_by_code: Mapping[str, str]
    parent_industries: tuple[ParentIndustry, ...]


@dataclass(frozen=True)
class HundredDayStockAnalysis:
    stock_code: str
    stock_name: str
    parent_industries: tuple[dict[str, str], ...]
    is_new_high: bool
    is_new_low: bool


@dataclass(frozen=True)
class HundredDayIndustryAnalysis:
    industry_code: str
    industry_name: str
    stock_count: int
    new_high_count: int
    new_low_count: int
    new_high_stocks: tuple[dict[str, str], ...]
    new_low_stocks: tuple[dict[str, str], ...]


@dataclass(frozen=True)
class HundredDayTrendAnalysis:
    trade_date: date
    valid_stock_count: int
    new_high_count: int
    new_low_count: int
    new_high_ratio: Decimal | None
    new_low_ratio: Decimal | None


@dataclass(frozen=True)
class HundredDayAnalysis:
    business_date: date
    source_daily_price_version: str
    source_industry_version: str
    valid_stock_count: int
    new_high_count: int
    new_low_count: int
    stock_flags: tuple[HundredDayStockAnalysis, ...]
    industry_summaries: tuple[HundredDayIndustryAnalysis, ...]
    trend_points: tuple[HundredDayTrendAnalysis, ...]


def _parent_industries_by_stock(
    industries: tuple[ParentIndustry, ...],
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
    return tuple(
        HundredDayStockAnalysis(
            stock_code=flag.stock_code,
            stock_name=source.stock_names_by_code.get(flag.stock_code, flag.stock_code),
            parent_industries=memberships.get(flag.stock_code, ()),
            is_new_high=flag.is_new_high,
            is_new_low=flag.is_new_low,
        )
        for flag in flags
    )


def _industry_summaries(
    *,
    stock_flags: tuple[HundredDayStockAnalysis, ...],
    valid_stock_codes: set[str],
    industries: tuple[ParentIndustry, ...],
) -> tuple[HundredDayIndustryAnalysis, ...]:
    flagged_by_stock = {flag.stock_code: flag for flag in stock_flags}
    summaries: list[HundredDayIndustryAnalysis] = []
    for industry in sorted(industries, key=lambda item: item.code):
        stock_codes = tuple(sorted(set(industry.stock_codes) & valid_stock_codes))
        high_stocks = tuple(
            {'code': stock_code, 'name': flagged_by_stock[stock_code].stock_name}
            for stock_code in stock_codes
            if stock_code in flagged_by_stock and flagged_by_stock[stock_code].is_new_high
        )
        low_stocks = tuple(
            {'code': stock_code, 'name': flagged_by_stock[stock_code].stock_name}
            for stock_code in stock_codes
            if stock_code in flagged_by_stock and flagged_by_stock[stock_code].is_new_low
        )
        if stock_codes or high_stocks or low_stocks:
            summaries.append(
                HundredDayIndustryAnalysis(
                    industry_code=industry.code,
                    industry_name=industry.name,
                    stock_count=len(stock_codes),
                    new_high_count=len(high_stocks),
                    new_low_count=len(low_stocks),
                    new_high_stocks=high_stocks,
                    new_low_stocks=low_stocks,
                )
            )
    return tuple(summaries)


def _trend_points(flag_result: HighLowFlagResult) -> tuple[HundredDayTrendAnalysis, ...]:
    trend_days = tuple(flag_result.flags_by_date)[-MAX_TREND_POINTS:]
    points = []
    for trade_date in trend_days:
        flags = flag_result.flags_by_date[trade_date]
        valid_stock_count = flag_result.valid_stock_counts_by_date[trade_date]
        new_high_count = sum(flag.is_new_high for flag in flags)
        new_low_count = sum(flag.is_new_low for flag in flags)
        points.append(
            HundredDayTrendAnalysis(
                trade_date=trade_date,
                valid_stock_count=valid_stock_count,
                new_high_count=new_high_count,
                new_low_count=new_low_count,
                new_high_ratio=(
                    Decimal(new_high_count) / Decimal(valid_stock_count)
                    if valid_stock_count else None
                ),
                new_low_ratio=(
                    Decimal(new_low_count) / Decimal(valid_stock_count)
                    if valid_stock_count else None
                ),
            )
        )
    return tuple(points)


def build_hundred_day_analysis(
    source: HistoricalCloseData, *, source_industry_version: str
) -> HundredDayAnalysis:
    """Build target-day stock and parent-industry results plus a bounded trend."""
    if not source.trading_days or source.trading_days[-1] != source.data_version.business_date:
        raise ValueError('The target daily-price version must match the final trading-day position.')
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

    business_date = source.data_version.business_date
    target_flags = flag_result.flags_by_date[business_date]
    memberships = _parent_industries_by_stock(source.parent_industries)
    stock_flags = _stock_analysis(target_flags, source, memberships)
    valid_stock_codes = {
        stock_code
        for stock_code, closes in source.close_prices_by_stock.items()
        if closes.get(business_date) is not None
    }
    trend_points = _trend_points(flag_result)
    return HundredDayAnalysis(
        business_date=business_date,
        source_daily_price_version=source.data_version.version,
        source_industry_version=source_industry_version,
        valid_stock_count=flag_result.valid_stock_counts_by_date[business_date],
        new_high_count=sum(flag.is_new_high for flag in target_flags),
        new_low_count=sum(flag.is_new_low for flag in target_flags),
        stock_flags=stock_flags,
        industry_summaries=_industry_summaries(
            stock_flags=stock_flags,
            valid_stock_codes=valid_stock_codes,
            industries=source.parent_industries,
        ),
        trend_points=trend_points,
    )
