"""Bounded local public-data loader for hundred-day analysis."""

from datetime import date

from core.models import DailyPrice
from core.services.calendar import recent_trading_days
from core.services.market_data import (
    CompleteMarketDataUnavailable,
    get_complete_market_snapshot,
)
from hundred_day.services.analysis import (
    HistoricalCloseData,
    MAX_INPUT_TRADING_DAY_POSITIONS,
    TargetDayQuote,
)


def _recent_trading_days(business_date: date) -> tuple[date, ...]:
    days = recent_trading_days(business_date, count=MAX_INPUT_TRADING_DAY_POSITIONS)
    return tuple(reversed(days))


def load_hundred_day_source_data(business_date: date) -> HistoricalCloseData:
    """Load no more than 199 local trading-day positions and their recorded closes."""
    target_snapshot = get_complete_market_snapshot(business_date)
    trading_days = _recent_trading_days(business_date)
    if not trading_days or trading_days[-1] != business_date:
        raise CompleteMarketDataUnavailable(f'{business_date.isoformat()} is not a trading day.')

    # 一天 5571 行 × 199 个交易日约 110 万行：逐对象构造 ORM 实例要 15 秒左右，
    # 批量取值只要不到 2 秒。这是请求内按需生成能接受的前提。
    #
    # 按交易日取值即可：公共日行情的唯一键是「股票 + 交易日」，同步命令对同一天
    # 是整批 upsert 覆盖，所以同一天不可能同时留着两套新旧不同的行。
    close_prices_by_stock: dict[str, dict] = {}
    stock_names_by_code: dict[str, str] = {}
    target_day_quotes: dict[str, TargetDayQuote] = {}
    rows = DailyPrice.objects.filter(trade_date__in=trading_days).values_list(
        'stock__stock_code',
        'stock__stock_name',
        'trade_date',
        'close_price',
        'has_valid_trade',
        'change_percent',
        'turnover',
    )
    for (
        stock_code,
        stock_name,
        trade_date,
        close_price,
        has_valid_trade,
        change_percent,
        turnover,
    ) in rows:
        stock_names_by_code[stock_code] = stock_name
        close_prices_by_stock.setdefault(stock_code, {})[trade_date] = (
            close_price if has_valid_trade else None
        )
        if trade_date == business_date:
            target_day_quotes[stock_code] = TargetDayQuote(
                change_percent=change_percent if has_valid_trade else None,
                turnover=turnover if has_valid_trade else None,
            )

    return HistoricalCloseData(
        business_date=business_date,
        trading_days=trading_days,
        close_prices_by_stock=close_prices_by_stock,
        stock_names_by_code=stock_names_by_code,
        industries=target_snapshot.industries,
        target_day_quotes=target_day_quotes,
    )
