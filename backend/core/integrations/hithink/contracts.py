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
