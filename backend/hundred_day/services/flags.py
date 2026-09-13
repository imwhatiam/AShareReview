"""Pure legacy-compatible hundred-day high/low flag calculation."""

from collections import deque
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


def _sliding_extrema(filled: list[Decimal], available_positions: int, window: int):
    """Yield ``(position, maximum, minimum)`` for each window of the preceding ``window`` days.

    ``filled`` is the stock's close series aligned to the trading days, with every
    missing value already replaced by zero. Both extrema come from the same
    ``window``-sized window ending at ``position - 1``, so two monotonic deques keep
    this linear in the number of positions instead of quadratic in the window length.
    Positions with fewer than ``window`` preceding days are skipped.
    """
    maximums: deque[int] = deque()
    minimums: deque[int] = deque()
    for index in range(available_positions - 1):
        value = filled[index]
        while maximums and filled[maximums[-1]] <= value:
            maximums.pop()
        maximums.append(index)
        while minimums and filled[minimums[-1]] >= value:
            minimums.pop()
        minimums.append(index)
        position = index + 1
        if position < window:
            continue
        lower_bound = position - window
        while maximums[0] < lower_bound:
            maximums.popleft()
        while minimums[0] < lower_bound:
            minimums.popleft()
        yield position, filled[maximums[0]], filled[minimums[0]]


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

    positions = range(ROLLING_HISTORY_POSITIONS, available_positions)
    flags_by_position: dict[int, list[HighLowFlag]] = {position: [] for position in positions}
    valid_stock_counts_by_position = dict.fromkeys(positions, 0)

    for stock_code in sorted(close_prices_by_stock):
        stock_closes = close_prices_by_stock[stock_code]
        # 历史窗口内缺失收盘价按既有规则补 0；目标日缺失仍然是"无有效成交"，不参与旗标。
        filled = [
            _ZERO if stock_closes.get(day) is None else stock_closes[day]
            for day in trading_days
        ]
        for position, historical_maximum, historical_minimum in _sliding_extrema(
            filled, available_positions, ROLLING_HISTORY_POSITIONS
        ):
            target_close = stock_closes.get(trading_days[position])
            if target_close is None:
                continue
            valid_stock_counts_by_position[position] += 1
            is_new_high = target_close >= historical_maximum
            is_new_low = target_close <= historical_minimum
            if is_new_high or is_new_low:
                flags_by_position[position].append(
                    HighLowFlag(
                        stock_code=stock_code,
                        is_new_high=is_new_high,
                        is_new_low=is_new_low,
                    )
                )

    flags_by_date = {
        trading_days[position]: tuple(flags_by_position[position])
        for position in positions
    }
    valid_stock_counts_by_date = {
        trading_days[position]: valid_stock_counts_by_position[position]
        for position in positions
    }
    return HighLowFlagResult(
        has_sufficient_history=True,
        required_trading_day_positions=_REQUIRED_TRADING_DAY_POSITIONS,
        available_trading_day_positions=available_positions,
        flags_by_date=flags_by_date,
        valid_stock_counts_by_date=valid_stock_counts_by_date,
    )
