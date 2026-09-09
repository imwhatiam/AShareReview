"""Convert documented Hithink REST payloads into internal contracts."""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from core.integrations.hithink.contracts import (
    HithinkPayloadError,
    HithinkPriceBar,
    HithinkTicker,
)


_SHANGHAI = ZoneInfo('Asia/Shanghai')
_EXCHANGES = {'SH': 'sse', 'SZ': 'szse', 'BJ': 'bse'}


def _required_string(item: dict, field: str) -> str:
    value = item.get(field)
    if not isinstance(value, str) or not value:
        raise HithinkPayloadError(f'Upstream field {field!r} is missing or invalid.')
    return value


def _required_integer(item: dict, field: str) -> int:
    value = item.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise HithinkPayloadError(f'Upstream field {field!r} is missing or invalid.')
    return value


def _decimal_or_none(item: dict, field: str) -> Decimal | None:
    value = item.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HithinkPayloadError(f'Upstream field {field!r} is invalid.')
    try:
        return Decimal(str(value))
    except InvalidOperation as error:
        raise HithinkPayloadError(
            f'Upstream field {field!r} is invalid.'
        ) from error


def _integer_or_none(item: dict, field: str) -> int | None:
    value = item.get(field)
    if value is None:
        return None
    if isinstance(value, bool):
        raise HithinkPayloadError(f'Upstream field {field!r} is invalid.')
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise HithinkPayloadError(f'Upstream field {field!r} is invalid.')


def _date_from_milliseconds(value: int):
    if isinstance(value, bool) or not isinstance(value, int):
        raise HithinkPayloadError('Upstream date_ms is missing or invalid.')
    try:
        return datetime.fromtimestamp(value / 1000, tz=_SHANGHAI).date()
    except (OverflowError, OSError, ValueError) as error:
        raise HithinkPayloadError('Upstream date_ms is invalid.') from error


def map_ticker(item: dict) -> HithinkTicker:
    if not isinstance(item, dict):
        raise HithinkPayloadError('Upstream ticker item is invalid.')
    exchange = _required_string(item, 'exchange')
    if exchange not in _EXCHANGES:
        raise HithinkPayloadError('Upstream ticker exchange is invalid.')
    return HithinkTicker(
        thscode=_required_string(item, 'thscode'),
        stock_code=_required_string(item, 'ticker'),
        stock_name=_required_string(item, 'name'),
        exchange=_EXCHANGES[exchange],
    )


def map_trading_day(item: dict):
    if not isinstance(item, dict):
        raise HithinkPayloadError('Upstream trading-day item is invalid.')
    compact_date = _required_string(item, 'date')
    timestamp_date = _date_from_milliseconds(_required_integer(item, 'date_ms'))
    try:
        parsed_date = datetime.strptime(compact_date, '%Y%m%d').date()
    except ValueError as error:
        raise HithinkPayloadError('Upstream trading-day date is invalid.') from error
    if parsed_date != timestamp_date:
        raise HithinkPayloadError('Upstream trading-day fields disagree.')
    return parsed_date


def map_price_bar(item: dict) -> HithinkPriceBar:
    if not isinstance(item, dict):
        raise HithinkPayloadError('Upstream historical price item is invalid.')
    return HithinkPriceBar(
        trade_date=_date_from_milliseconds(_required_integer(item, 'date_ms')),
        open_price=_decimal_or_none(item, 'open_price'),
        high_price=_decimal_or_none(item, 'high_price'),
        low_price=_decimal_or_none(item, 'low_price'),
        close_price=_decimal_or_none(item, 'close_price'),
        volume=_integer_or_none(item, 'volume'),
        turnover=_decimal_or_none(item, 'turnover'),
    )
