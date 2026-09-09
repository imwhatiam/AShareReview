"""Bounded REST client for Hithink public A-share market data."""

from dataclasses import dataclass
from datetime import date, datetime, time
from time import sleep
from typing import Any
from zoneinfo import ZoneInfo

import requests
from django.core.exceptions import ImproperlyConfigured

from backend.env import get_required_setting
from core.integrations.hithink.contracts import (
    HithinkAuthenticationError,
    HithinkPayloadError,
    HithinkRateLimitError,
    HithinkUnavailableError,
)
from core.integrations.hithink.mappers import (
    map_price_bar,
    map_ticker,
    map_trading_day,
)


_SHANGHAI = ZoneInfo('Asia/Shanghai')


@dataclass(frozen=True)
class _ClientSettings:
    base_url: str
    api_key: str
    timeout_seconds: int
    request_delay_seconds: float
    max_retries: int


def _positive_integer_setting(name: str, *, minimum: int = 0) -> int:
    value = get_required_setting(name)
    try:
        parsed = int(value)
    except ValueError as error:
        raise ImproperlyConfigured(f'{name} must be an integer.') from error
    if parsed < minimum:
        raise ImproperlyConfigured(f'{name} must be at least {minimum}.')
    return parsed


def _settings() -> _ClientSettings:
    delay = get_required_setting('HITHINK_FINANCE_REQUEST_DELAY_SECONDS')
    try:
        request_delay_seconds = float(delay)
    except ValueError as error:
        raise ImproperlyConfigured(
            'HITHINK_FINANCE_REQUEST_DELAY_SECONDS must be numeric.'
        ) from error
    if request_delay_seconds < 0:
        raise ImproperlyConfigured(
            'HITHINK_FINANCE_REQUEST_DELAY_SECONDS must not be negative.'
        )
    return _ClientSettings(
        base_url=get_required_setting('HITHINK_FINANCE_BASE_URL').rstrip('/'),
        api_key=get_required_setting('HITHINK_FINANCE_API_KEY'),
        timeout_seconds=_positive_integer_setting(
            'HITHINK_FINANCE_TIMEOUT_SECONDS', minimum=1
        ),
        request_delay_seconds=request_delay_seconds,
        max_retries=_positive_integer_setting('HITHINK_FINANCE_MAX_RETRIES'),
    )


def _market_timestamp(value: date) -> int:
    return int(datetime.combine(value, time.min, tzinfo=_SHANGHAI).timestamp() * 1000)


class HithinkClient:
    def __init__(self, transport=None):
        self._settings = _settings()
        self._transport = transport or requests.Session()

    def list_a_share_tickers(self, *, limit: int, offset: int):
        if not 1 <= limit <= 10000 or offset < 0:
            raise ValueError('Ticker pagination is outside the upstream range.')
        data = self._get(
            '/api/meta/tickers/list',
            {
                'asset_type': 'a-share',
                'exchange': 'SH,SZ,BJ',
                'limit': limit,
                'offset': offset,
            },
        )
        return tuple(map_ticker(item) for item in self._items(data))

    def list_trading_days(self):
        data = self._get('/api/a-share/calendar/trading-days', {})
        return tuple(map_trading_day(item) for item in self._items(data))

    def get_historical_prices(
        self, thscode: str, *, start_date: date, end_date: date
    ):
        if not thscode or ',' in thscode or start_date > end_date:
            raise ValueError('Historical price request is invalid.')
        data = self._get(
            '/api/a-share/prices/historical',
            {
                'thscode': thscode,
                'interval': '1d',
                'start': _market_timestamp(start_date),
                'end': _market_timestamp(end_date),
                'adjust': 'forward',
                'offset': 0,
            },
        )
        return tuple(map_price_bar(item) for item in self._items(data))

    def _get(self, path: str, params: dict[str, Any]) -> dict:
        for attempt in range(self._settings.max_retries + 1):
            try:
                try:
                    response = self._transport.get(
                        f'{self._settings.base_url}{path}',
                        headers={'X-api-key': self._settings.api_key},
                        params=params,
                        timeout=self._settings.timeout_seconds,
                    )
                except requests.RequestException as error:
                    raise HithinkUnavailableError(
                        'Hithink REST is temporarily unavailable.'
                    ) from error
                return self._parse_response(response)
            except (HithinkRateLimitError, HithinkUnavailableError):
                if attempt == self._settings.max_retries:
                    raise
                sleep(self._settings.request_delay_seconds)

        raise AssertionError('Bounded request loop unexpectedly ended.')

    def _parse_response(self, response) -> dict:
        if response.status_code == 429:
            raise HithinkRateLimitError('Hithink REST rate limit exceeded.')
        if response.status_code in {401, 403}:
            raise HithinkAuthenticationError('Hithink REST authentication failed.')
        if not 200 <= response.status_code < 300:
            raise HithinkUnavailableError('Hithink REST request failed.')
        try:
            payload = response.json()
        except ValueError as error:
            raise HithinkPayloadError('Hithink REST returned invalid JSON.') from error
        if not isinstance(payload, dict) or isinstance(payload.get('code'), bool):
            raise HithinkPayloadError('Hithink REST response envelope is invalid.')

        code = payload.get('code')
        if code == 0:
            data = payload.get('data')
            if not isinstance(data, dict):
                raise HithinkPayloadError('Hithink REST response data is invalid.')
            return data
        if code == 4001:
            raise HithinkRateLimitError('Hithink REST rate limit exceeded.')
        if code in {2001, 2003}:
            raise HithinkAuthenticationError('Hithink REST authentication failed.')
        if code in {5001, 5002, 5003}:
            raise HithinkUnavailableError('Hithink REST is temporarily unavailable.')
        raise HithinkUnavailableError('Hithink REST request was rejected.')

    @staticmethod
    def _items(data: dict) -> list[dict]:
        items = data.get('item')
        if not isinstance(items, list):
            raise HithinkPayloadError('Hithink REST response item is invalid.')
        return items
