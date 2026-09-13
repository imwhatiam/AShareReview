"""Internal contracts and errors for the Hithink REST integration."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


class HithinkError(RuntimeError):
    """Base error for a failed Hithink REST request."""


class HithinkAuthenticationError(HithinkError):
    """The configured API key was rejected or lacks permission."""


class HithinkRateLimitError(HithinkError):
    """The upstream service rejected the request because of rate limits."""


class HithinkUnavailableError(HithinkError):
    """The upstream service or network is temporarily unavailable."""


class HithinkPayloadError(HithinkError):
    """The upstream response does not satisfy the documented contract."""


@dataclass(frozen=True)
class HithinkTicker:
    thscode: str
    stock_code: str
    stock_name: str
    exchange: str


@dataclass(frozen=True)
class HithinkPriceBar:
    trade_date: date
    open_price: Decimal | None
    high_price: Decimal | None
    low_price: Decimal | None
    close_price: Decimal | None
    volume: int | None
    turnover: Decimal | None


@dataclass(frozen=True)
class HithinkQuoteSnapshot:
    """One row of the whole-market intraday quote snapshot.

    ``last_price`` is ``None`` while a stock is suspended, which is the only
    reliable way the snapshot marks "no trade today": a suspended stock still
    appears in the payload, but with a null price and zero volume.

    The upstream also publishes ``price_change`` / ``price_change_ratio_pct``,
    and those are deliberately not carried here. On an ex-dividend day the
    snapshot reports them against the *unadjusted* previous close, whereas the
    stored daily-price series is forward adjusted, so the pipeline always
    recomputes the percentage from the stored previous close instead.
    """

    thscode: str
    stock_code: str
    last_price: Decimal | None
    open_price: Decimal | None
    high_price: Decimal | None
    low_price: Decimal | None
    volume: int | None
    turnover: Decimal | None


@dataclass(frozen=True)
class HithinkIndustryIndex:
    """One Tonghuashun industry index, e.g. ``881121.TI`` for semiconductors.

    ``industry_code`` drops the ``.TI`` market suffix so it can be compared with
    the industry codes other upstreams publish.
    """

    thscode: str
    industry_code: str
    industry_name: str
