import re
from datetime import date

from core.api.errors import ApiError, ErrorCode


_ALLOWED_WINDOW_DAYS = {1, 5, 10, 20}


def parse_iso_date(value: str) -> date:
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ApiError(ErrorCode.INVALID_DATE, '日期必须为 YYYY-MM-DD 格式。')
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ApiError(ErrorCode.INVALID_DATE, '日期必须为 YYYY-MM-DD 格式。') from error


def _parse_bounded_integer(value: str, name: str, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as error:
        raise ApiError(ErrorCode.INVALID_PARAMETER, f'{name} 参数无效。') from error
    if not minimum <= number <= maximum:
        raise ApiError(ErrorCode.INVALID_PARAMETER, f'{name} 参数超出允许范围。')
    return number


def parse_window_days(value: str) -> int:
    days = _parse_bounded_integer(value, 'days', min(_ALLOWED_WINDOW_DAYS), max(_ALLOWED_WINDOW_DAYS))
    if days not in _ALLOWED_WINDOW_DAYS:
        raise ApiError(ErrorCode.INVALID_PARAMETER, 'days 仅支持 1、5、10 或 20。')
    return days


def parse_rank_count(value: str, name: str) -> int:
    return _parse_bounded_integer(value, name, 0, 30)
