from datetime import date, datetime

from core.models import DailyPrice, DataVersion, IndustrySnapshot
from core.services.calendar import latest_eligible_trading_day, to_shanghai_date
from core.services.contracts import (
    CompleteMarketSnapshot,
    Industry,
    MarketDataVersion,
    MarketPrice,
)


STOCK_DAILY_PRICES_DATASET = 'stock_daily_prices'


class CompleteMarketDataUnavailable(LookupError):
    """Raised when no complete public daily-price version is available."""


def latest_complete_stock_price_date(now: datetime | None = None) -> date | None:
    """Return the trading day the default page entry should read.

    ``latest_eligible_trading_day`` answers "has the *current* session closed",
    which is what the post-close pipeline needs, so before 15:00 it deliberately
    steps back one day. A page needs a different question answered: "is there a
    complete version for today yet". An intraday refresh publishes exactly such
    a version, and once one exists the default entry must follow today —
    otherwise the store is being updated every half hour while every page keeps
    showing yesterday.

    The upper bound is only relaxed when today already carries a complete
    version, so before the first intraday refresh (and on every non-trading day)
    the behaviour is unchanged.
    """
    eligible_day = latest_eligible_trading_day(now)
    if eligible_day is None:
        return None
    today = to_shanghai_date(now)
    if eligible_day >= today:
        upper_bound = eligible_day
    elif _has_complete_version(today):
        upper_bound = today
    else:
        upper_bound = eligible_day
    version = (
        DataVersion.objects.filter(
            dataset_key=STOCK_DAILY_PRICES_DATASET,
            status=DataVersion.Status.COMPLETE,
            business_date__lte=upper_bound,
        )
        .order_by('-business_date', '-last_success_at', '-started_at')
        .first()
    )
    return version.business_date if version is not None else None


def _has_complete_version(business_date: date) -> bool:
    return DataVersion.objects.filter(
        dataset_key=STOCK_DAILY_PRICES_DATASET,
        status=DataVersion.Status.COMPLETE,
        business_date=business_date,
    ).exists()


def get_complete_market_snapshot(business_date: date) -> CompleteMarketSnapshot:
    version = (
        DataVersion.objects.filter(
            dataset_key=STOCK_DAILY_PRICES_DATASET,
            status=DataVersion.Status.COMPLETE,
            business_date=business_date,
        )
        .order_by('-last_success_at', '-started_at')
        .first()
    )
    if version is None:
        raise CompleteMarketDataUnavailable(
            f'No complete daily-price version exists for {business_date.isoformat()}.'
        )

    prices = tuple(
        MarketPrice(
            stock_code=record.stock.stock_code,
            thscode=record.stock.thscode,
            stock_name=record.stock.stock_name,
            exchange=record.stock.exchange,
            trade_date=record.trade_date,
            pre_close=record.pre_close,
            open_price=record.open_price,
            high_price=record.high_price,
            low_price=record.low_price,
            close_price=record.close_price,
            change_percent=record.change_percent,
            volume=record.volume,
            turnover=record.turnover,
            has_valid_trade=record.has_valid_trade,
        )
        for record in DailyPrice.objects.filter(
            trade_date=business_date,
            source_data_version=version.version,
        ).select_related('stock')
    )
    industries = tuple(
        Industry(
            code=industry.industry_code,
            name=industry.industry_name,
            stock_codes=tuple(industry.stock_codes),
        )
        for industry in IndustrySnapshot.objects.all()
    )
    return CompleteMarketSnapshot(
        data_version=MarketDataVersion(
            version=version.version,
            business_date=version.business_date,
        ),
        prices=prices,
        industries=industries,
    )
