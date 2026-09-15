"""Bounded REST client for Hithink public A-share market data."""

import logging
from dataclasses import dataclass
from datetime import date, datetime, time
from time import perf_counter, sleep
from typing import Any
from zoneinfo import ZoneInfo

import requests

from backend.env import get_required_float_setting, get_required_int_setting, get_required_setting
from core.api.errors import upstream_error_code_value
from core.integrations.hithink.contracts import (
    HithinkAuthenticationError,
    HithinkPayloadError,
    HithinkRateLimitError,
    HithinkUnavailableError,
)
from core.integrations.hithink.mappers import (
    map_industry_constituent,
    map_industry_index,
    map_price_bar,
    map_quote_snapshot,
    map_ticker,
)
from core.logging import elapsed_ms, log_event


logger = logging.getLogger(__name__)

_SHANGHAI = ZoneInfo('Asia/Shanghai')
# 同花顺指数清单按标签分族：industry 是 881xxx 行业，cn_concept 是概念。
_INDUSTRY_INDEX_TAG = 'industry'


@dataclass(frozen=True)
class _ClientSettings:
    base_url: str
    api_key: str
    timeout_seconds: int
    request_delay_seconds: float
    max_retries: int


def _settings() -> _ClientSettings:
    return _ClientSettings(
        base_url=get_required_setting('HITHINK_FINANCE_BASE_URL').rstrip('/'),
        api_key=get_required_setting('HITHINK_FINANCE_API_KEY'),
        timeout_seconds=get_required_int_setting('HITHINK_FINANCE_TIMEOUT_SECONDS', minimum=1),
        request_delay_seconds=get_required_float_setting('HITHINK_FINANCE_REQUEST_DELAY_SECONDS'),
        max_retries=get_required_int_setting('HITHINK_FINANCE_MAX_RETRIES'),
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

    def list_industry_indices(self):
        """Return every Tonghuashun industry index (881xxx.TI / 884xxx.TI).

        The upstream endpoint has no pagination: one call returns the whole tag.
        """
        data = self._get(
            '/api/a-share-index/catalog/ths-index-list',
            {'tag': _INDUSTRY_INDEX_TAG},
        )
        return tuple(map_industry_index(item) for item in self._items(data))

    def list_industry_constituents(self, thscode: str):
        """Return the constituent stock codes of one Tonghuashun industry index.

        The upstream rejects comma-separated lists (``code=1002``), so callers
        must request one index at a time. The list is the current membership —
        the endpoint accepts no date and always answers for the latest state.
        """
        if not thscode or ',' in thscode:
            raise ValueError('Industry constituent request is invalid.')
        data = self._get(
            '/api/a-share-index/constituents/ths-stock-list',
            {'thscode': thscode},
        )
        return tuple(map_industry_constituent(item) for item in self._items(data))

    def list_market_quotes(self, *, limit: int, offset: int):
        """Return one page of the whole-market intraday quote snapshot.

        ``thscodes`` is deliberately omitted: that makes the upstream walk the
        complete A-share code table (ascending ``thscode``) and page it by
        ``limit`` / ``offset``. One page of a thousand covers a fifth of the
        market, versus one request per stock for the historical endpoint — the
        difference between a two-second refresh and a six-minute one.

        The upstream ``total`` is returned as a paging hint only; callers must
        still stop on a short or empty page, because a stale ``total`` would
        otherwise spin the loop forever.
        """
        if not 1 <= limit <= 10000 or offset < 0:
            raise ValueError('Quote snapshot pagination is outside the upstream range.')
        data = self._get(
            '/api/a-share/prices/snapshot',
            {'limit': limit, 'offset': offset},
        )
        total = data.get('total')
        if isinstance(total, bool) or not isinstance(total, int) or total < 0:
            total = None
        return tuple(map_quote_snapshot(item) for item in self._items(data)), total

    def _get(self, path: str, params: dict[str, Any]) -> dict:
        # 上游调用是整个系统最容易失败的地方，也是唯一"重试"发生的地方：每次重试
        # 记一行 WARNING（含原因），最终放弃记 ERROR。成功的调用只记 DEBUG ——
        # 一次同步会打几千次，INFO 会把日志淹掉，而耗时在命令级的进度日志里已有。
        started_at = perf_counter()
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
                data = self._parse_response(response)
            except (HithinkRateLimitError, HithinkUnavailableError) as error:
                if attempt == self._settings.max_retries:
                    log_event(
                        logger,
                        'upstream_failed',
                        level=logging.ERROR,
                        provider='hithink',
                        path=path,
                        attempts=attempt + 1,
                        duration_ms=elapsed_ms(started_at),
                        error=error,
                        error_code=upstream_error_code_value(error),
                    )
                    raise
                log_event(
                    logger,
                    'upstream_retry',
                    level=logging.WARNING,
                    provider='hithink',
                    path=path,
                    attempt=attempt + 1,
                    retry_delay_seconds=self._settings.request_delay_seconds,
                    reason=error,
                )
                sleep(self._settings.request_delay_seconds)
                continue
            logger.debug(
                '%s provider=hithink path=%s duration_ms=%s',
                'upstream_ok',
                path,
                elapsed_ms(started_at),
            )
            return data

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
