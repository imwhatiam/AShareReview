"""Bounded local public-data loader for hundred-day analysis."""

from datetime import date

from core.models import DailyPrice, DataVersion, TradingDay
from core.services.contracts import MarketDataVersion
from core.services.market_data import (
    STOCK_DAILY_PRICES_DATASET,
    CompleteMarketDataUnavailable,
    get_complete_market_snapshot,
)
from hundred_day.services.analysis import HistoricalCloseData, MAX_INPUT_TRADING_DAY_POSITIONS


def _recent_trading_days(business_date: date) -> tuple[date, ...]:
    dates = list(
        TradingDay.objects.filter(trade_date__lte=business_date)
        .order_by('-trade_date')
        .values_list('trade_date', flat=True)[:MAX_INPUT_TRADING_DAY_POSITIONS]
    )
    return tuple(reversed(dates))


def load_hundred_day_source_data(business_date: date) -> HistoricalCloseData:
    """Load no more than 199 local calendar positions and their recorded closes."""
    target_snapshot = get_complete_market_snapshot(business_date)
    trading_days = _recent_trading_days(business_date)
    if not trading_days or trading_days[-1] != business_date:
        raise CompleteMarketDataUnavailable(
            f'No local trading-calendar position exists for {business_date.isoformat()}.'
        )

    completed_dates = set(
        DataVersion.objects.filter(
            dataset_key=STOCK_DAILY_PRICES_DATASET,
            status=DataVersion.Status.COMPLETE,
            business_date__in=trading_days,
        ).values_list('business_date', flat=True)
    )
    missing_dates = set(trading_days) - completed_dates
    if missing_dates:
        earliest_missing = min(missing_dates)
        raise CompleteMarketDataUnavailable(
            'No complete local daily-price version exists for trading-day position '
            f'{earliest_missing.isoformat()}.'
        )

    close_prices_by_stock: dict[str, dict] = {}
    stock_names_by_code: dict[str, str] = {}
    for price in DailyPrice.objects.filter(trade_date__in=trading_days).select_related('stock'):
        stock_code = price.stock.stock_code
        stock_names_by_code[stock_code] = price.stock.stock_name
        close_prices_by_stock.setdefault(stock_code, {})[price.trade_date] = (
            price.close_price if price.has_valid_trade else None
        )

    return HistoricalCloseData(
        data_version=MarketDataVersion(
            version=target_snapshot.data_version.version,
            business_date=business_date,
        ),
        trading_days=trading_days,
        close_prices_by_stock=close_prices_by_stock,
        stock_names_by_code=stock_names_by_code,
        parent_industries=target_snapshot.parent_industries,
    )
