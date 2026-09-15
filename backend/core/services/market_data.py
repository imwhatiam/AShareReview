from datetime import date, datetime

from django.db.models import Max

from core.models import DailyPrice, IndustrySnapshot
from core.services.calendar import latest_eligible_trading_day, to_shanghai_date
from core.services.contracts import CompleteMarketSnapshot, Industry, MarketPrice


class CompleteMarketDataUnavailable(LookupError):
    """Raised when a trading day has no stored public daily prices."""


def latest_complete_stock_price_date(now: datetime | None = None) -> date | None:
    """Return the trading day the default page entry should read.

    ``latest_eligible_trading_day`` answers "has the *current* session closed",
    which is what the post-close pipeline needs, so before 15:00 it deliberately
    steps back one day. A page needs a different question answered: "are today's
    prices already stored". An intraday refresh writes exactly such rows, and
    once they exist the default entry must follow today — otherwise the store is
    being updated every half hour while every page keeps showing yesterday.

    The upper bound is only relaxed when today already carries prices, so before
    the first intraday refresh (and on every non-trading day) the behaviour is
    unchanged.
    """
    eligible_day = latest_eligible_trading_day(now)
    today = to_shanghai_date(now)
    if eligible_day < today and has_stock_prices(today):
        upper_bound = today
    else:
        upper_bound = eligible_day
    return (
        DailyPrice.objects.filter(trade_date__lte=upper_bound)
        .aggregate(newest=Max('trade_date'))['newest']
    )


def has_stock_prices(business_date: date) -> bool:
    return DailyPrice.objects.filter(trade_date=business_date).exists()


def resolve_business_date(requested: date | None) -> date:
    """Resolve an optional ``--date`` to the business date the read path serves.

    ``--date`` is optional on the three ``build_*`` commands precisely so that a
    scheduler does not have to work out "which trading day is this" in shell: the
    answer already exists here and is the same anchor the pages use
    (:func:`latest_complete_stock_price_date`). That matters on a Sunday, when a
    full-window revision writes the *previous* Friday's rows — the day to rebuild
    is Friday, not the calendar date the job happened to run on.
    """
    resolved = requested or latest_complete_stock_price_date()
    if resolved is None:
        raise ValueError('No public daily prices are stored yet.')
    return resolved


def get_complete_market_snapshot(business_date: date) -> CompleteMarketSnapshot:
    """Read one trading day's prices and the current industry mapping.

    The day's rows *are* the publication record: the sync commands validate
    coverage before writing and write the whole day in one transaction, so the
    presence of rows means the day is complete. Nothing is filtered by a version
    string because there is no version to filter by.
    """
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
            trade_date=business_date
        ).select_related('stock')
    )
    if not prices:
        raise CompleteMarketDataUnavailable(
            f'No daily prices are stored for {business_date.isoformat()}.'
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
        business_date=business_date,
        prices=prices,
        industries=industries,
    )
