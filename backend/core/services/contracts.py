from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class MarketPrice:
    stock_code: str
    thscode: str
    stock_name: str
    exchange: str
    trade_date: date
    pre_close: Decimal | None
    open_price: Decimal | None
    high_price: Decimal | None
    low_price: Decimal | None
    close_price: Decimal | None
    change_percent: Decimal | None
    volume: int | None
    turnover: Decimal | None
    has_valid_trade: bool


@dataclass(frozen=True)
class Industry:
    code: str
    name: str
    stock_codes: tuple[str, ...]


@dataclass(frozen=True)
class CompleteMarketSnapshot:
    business_date: date
    prices: tuple[MarketPrice, ...]
    industries: tuple[Industry, ...]
