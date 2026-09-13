"""Convert documented Hithink REST payloads into internal contracts."""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from core.integrations.hithink.contracts import (
    HithinkIndustryIndex,
    HithinkPayloadError,
    HithinkPriceBar,
    HithinkQuoteSnapshot,
    HithinkTicker,
)


_SHANGHAI = ZoneInfo('Asia/Shanghai')
_EXCHANGES = {'SH': 'sse', 'SZ': 'szse', 'BJ': 'bse'}
# 同花顺指数的市场后缀；只接受它才能保证拿到的是同花顺行业板块而不是交易所指数。
_INDEX_MARKET_SUFFIX = 'TI'


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


def map_quote_snapshot(item: dict) -> HithinkQuoteSnapshot:
    """Map one whole-market snapshot row.

    A suspended stock legitimately arrives as ``last_price: null``, so the price
    fields stay ``None`` here instead of raising — the service layer turns that
    into ``has_valid_trade=False``.
    """
    if not isinstance(item, dict):
        raise HithinkPayloadError('Upstream quote snapshot item is invalid.')
    return HithinkQuoteSnapshot(
        thscode=_required_string(item, 'thscode'),
        stock_code=_required_string(item, 'ticker'),
        last_price=_decimal_or_none(item, 'last_price'),
        open_price=_decimal_or_none(item, 'open_price'),
        high_price=_decimal_or_none(item, 'high_price'),
        low_price=_decimal_or_none(item, 'low_price'),
        volume=_integer_or_none(item, 'volume'),
        turnover=_decimal_or_none(item, 'turnover'),
    )


def map_industry_index(item: dict) -> HithinkIndustryIndex:
    if not isinstance(item, dict):
        raise HithinkPayloadError('Upstream industry index item is invalid.')
    thscode = _required_string(item, 'thscode')
    industry_code, separator, market = thscode.partition('.')
    if not industry_code or separator != '.' or market != _INDEX_MARKET_SUFFIX:
        raise HithinkPayloadError('Upstream industry index thscode is invalid.')
    return HithinkIndustryIndex(
        thscode=thscode,
        industry_code=industry_code,
        industry_name=_required_string(item, 'name'),
    )


def map_industry_constituent(item: dict) -> str:
    if not isinstance(item, dict):
        raise HithinkPayloadError('Upstream industry constituent item is invalid.')
    return _required_string(item, 'ticker')
