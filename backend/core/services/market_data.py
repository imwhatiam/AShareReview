from datetime import date, datetime

from core.models import DailyPrice, DataVersion, IndustrySnapshot
from core.services.calendar import latest_eligible_trading_day
from core.services.contracts import (
    CompleteMarketSnapshot,
    MarketDataVersion,
    MarketPrice,
    ParentIndustry,
)


STOCK_DAILY_PRICES_DATASET = 'stock_daily_prices'


class CompleteMarketDataUnavailable(LookupError):
    """Raised when no complete public daily-price version is available."""


def latest_complete_stock_price_date(now: datetime | None = None) -> date | None:
    eligible_day = latest_eligible_trading_day(now)
    if eligible_day is None:
        return None
    version = (
        DataVersion.objects.filter(
            dataset_key=STOCK_DAILY_PRICES_DATASET,
            status=DataVersion.Status.COMPLETE,
            business_date__lte=eligible_day,
        )
        .order_by('-business_date', '-last_success_at', '-started_at')
        .first()
    )
    return version.business_date if version is not None else None


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
    parent_industries = tuple(
        ParentIndustry(
            code=industry.industry_code,
            name=industry.industry_name,
            stock_codes=tuple(industry.stock_codes),
        )
        for industry in IndustrySnapshot.objects.filter(
            industry_level=IndustrySnapshot.Level.PARENT
        )
    )
    return CompleteMarketSnapshot(
        data_version=MarketDataVersion(
            version=version.version,
            business_date=version.business_date,
        ),
        prices=prices,
        parent_industries=parent_industries,
    )
