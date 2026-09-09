"""Pure legacy-compatible hundred-day high/low flag calculation."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Mapping


ROLLING_HISTORY_POSITIONS = 99
_REQUIRED_TRADING_DAY_POSITIONS = ROLLING_HISTORY_POSITIONS + 1
_ZERO = Decimal('0')


@dataclass(frozen=True)
class HighLowFlag:
    """One stock's inclusive high/low outcome for one target date."""

    stock_code: str
    is_new_high: bool
    is_new_low: bool


@dataclass(frozen=True)
class HighLowFlagResult:
    """Flags and explicit history availability for every evaluable date."""

    has_sufficient_history: bool
    required_trading_day_positions: int
    available_trading_day_positions: int
    flags_by_date: dict[date, tuple[HighLowFlag, ...]]
    valid_stock_counts_by_date: dict[date, int]


def _validate_trading_days(trading_days: tuple[date, ...]) -> None:
    if tuple(sorted(trading_days)) != trading_days:
        raise ValueError('Trading days must be in ascending order.')
    if len(set(trading_days)) != len(trading_days):
        raise ValueError('Trading days must not contain duplicates.')


def _history_extrema(
    stock_closes: Mapping[date, Decimal | None], history_days: tuple[date, ...]
) -> tuple[Decimal, Decimal]:
    """Return max/min after applying the legacy fill-missing-history-with-zero rule."""
    history = tuple(
        _ZERO if stock_closes.get(day) is None else stock_closes[day]
        for day in history_days
    )
    return max(history), min(history)


def compute_high_low_flags(
    trading_days: tuple[date, ...],
    close_prices_by_stock: Mapping[str, Mapping[date, Decimal | None]],
) -> HighLowFlagResult:
    """Mirror ``fillna(0).shift(1).rolling(99)`` without requiring pandas.

    ``None`` represents a missing close.  It is converted to zero only when it
    occurs in the preceding 99 trading-day positions.  A missing close at the
    target date is never filled and therefore produces no flag.
    """
    _validate_trading_days(trading_days)
    available_positions = len(trading_days)
    if available_positions < _REQUIRED_TRADING_DAY_POSITIONS:
        return HighLowFlagResult(
            has_sufficient_history=False,
            required_trading_day_positions=_REQUIRED_TRADING_DAY_POSITIONS,
            available_trading_day_positions=available_positions,
            flags_by_date={},
            valid_stock_counts_by_date={},
        )

    flags_by_date: dict[date, tuple[HighLowFlag, ...]] = {}
    valid_stock_counts_by_date: dict[date, int] = {}
    for position in range(ROLLING_HISTORY_POSITIONS, available_positions):
        target_day = trading_days[position]
        history_days = trading_days[position - ROLLING_HISTORY_POSITIONS:position]
        flags: list[HighLowFlag] = []
        valid_stock_count = 0
        for stock_code in sorted(close_prices_by_stock):
            stock_closes = close_prices_by_stock[stock_code]
            target_close = stock_closes.get(target_day)
            if target_close is None:
                continue
            valid_stock_count += 1
            historical_maximum, historical_minimum = _history_extrema(
                stock_closes, history_days
            )
            is_new_high = target_close >= historical_maximum
            is_new_low = target_close <= historical_minimum
            if is_new_high or is_new_low:
                flags.append(
                    HighLowFlag(
                        stock_code=stock_code,
                        is_new_high=is_new_high,
                        is_new_low=is_new_low,
                    )
                )
        flags_by_date[target_day] = tuple(flags)
        valid_stock_counts_by_date[target_day] = valid_stock_count

    return HighLowFlagResult(
        has_sufficient_history=True,
        required_trading_day_positions=_REQUIRED_TRADING_DAY_POSITIONS,
        available_trading_day_positions=available_positions,
        flags_by_date=flags_by_date,
        valid_stock_counts_by_date=valid_stock_counts_by_date,
    )
