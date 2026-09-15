"""Bounded Kaipanla client for the public industry-to-stock snapshot."""

import logging
from dataclasses import dataclass
import re
from time import perf_counter, sleep
from typing import Any

import requests

from backend.env import (
    get_required_float_setting,
    get_required_int_setting,
    get_required_setting,
    get_setting,
)
from core.api.errors import upstream_error_code_value
from core.integrations.kaipanla.contracts import (
    KaipanlaPayloadError,
    KaipanlaRateLimitError,
    KaipanlaUnavailableError,
    request_headers,
)
from core.logging import elapsed_ms, log_event, redact_sensitive_text
from core.services.calendar import latest_trading_date


logger = logging.getLogger(__name__)


def _upstream_error_detail(error_code: str, error_message) -> str:
    """Render an upstream business error so an operator can act on it.

    The raw envelope carries the reason (e.g. ``errcode 1020 参数出错`` for a
    ``Date`` the history endpoint will not serve); swallowing it leaves only
    "request was rejected", which is unactionable.
    """
    fields = [f'errcode={error_code or "unknown"}']
    message = ' '.join(redact_sensitive_text(error_message or '').split())
    if message:
        fields.append(f'errmsg={message[:120]}')
    return ' (' + ', '.join(fields) + ')'


@dataclass(frozen=True)
class _ClientSettings:
    endpoint: str
    device_id: str
    user_id: str
    token: str
    version: str
    api_version: str
    phone_os_new: str
    timeout_seconds: int
    request_delay_seconds: float
    max_retries: int
    parent_page_size: int
    stock_page_size: int
    controller: str
    parent_order: str
    parent_type: str
    parent_zs_type: str
    stock_order: str
    stock_tszb: str
    stock_old: str
    stock_is_zz: str
    stock_type: str
    stock_is_kzz_type: str


def _settings() -> _ClientSettings:
    return _ClientSettings(
        endpoint=get_required_setting('KAIPANLA_INDUSTRY_API_URL'),
        device_id=get_setting('KPL_DEVICE_ID', '') or '',
        user_id=get_setting('KPL_USER_ID', '') or '',
        token=get_setting('KPL_TOKEN', '') or '',
        version=get_required_setting('KPL_VERSION'),
        api_version=get_required_setting('KPL_API_VERSION'),
        phone_os_new=get_required_setting('KPL_PHONE_OS_NEW'),
        timeout_seconds=get_required_int_setting('KAIPANLA_TIMEOUT_SECONDS', minimum=1),
        request_delay_seconds=get_required_float_setting('KAIPANLA_REQUEST_DELAY_SECONDS'),
        max_retries=get_required_int_setting('KAIPANLA_MAX_RETRIES'),
        parent_page_size=get_required_int_setting(
            'KAIPANLA_INDUSTRY_PARENT_PAGE_SIZE', minimum=1
        ),
        stock_page_size=get_required_int_setting(
            'KAIPANLA_INDUSTRY_STOCK_PAGE_SIZE', minimum=1
        ),
        controller=get_required_setting('KAIPANLA_INDUSTRY_CONTROLLER'),
        parent_order=get_required_setting('KAIPANLA_INDUSTRY_PARENT_ORDER'),
        parent_type=get_required_setting('KAIPANLA_INDUSTRY_PARENT_TYPE'),
        parent_zs_type=get_required_setting('KAIPANLA_INDUSTRY_PARENT_ZS_TYPE'),
        stock_order=get_required_setting('KAIPANLA_INDUSTRY_STOCK_ORDER'),
        stock_tszb=get_required_setting('KAIPANLA_INDUSTRY_STOCK_TSZB'),
        stock_old=get_required_setting('KAIPANLA_INDUSTRY_STOCK_OLD'),
        stock_is_zz=get_required_setting('KAIPANLA_INDUSTRY_STOCK_IS_ZZ'),
        stock_type=get_required_setting('KAIPANLA_INDUSTRY_STOCK_TYPE'),
        stock_is_kzz_type=get_required_setting('KAIPANLA_INDUSTRY_STOCK_IS_KZZ_TYPE'),
    )


class KaipanlaIndustryClient:
    def __init__(self, transport=None):
        self._settings = _settings()
        self._transport = transport or requests.Session()
        # Resolved once per client so a paginated run does not re-query the calendar.
        self._request_date_value = None

    @property
    def request_date(self) -> str:
        """The ``Date`` this client sends, exposed for the caller's own use."""
        return self._request_date()

    def list_industries(self):
        return self._list_industries(
            action=get_required_setting('KAIPANLA_PARENT_INDUSTRY_ACTION'),
            response_key='list',
            params={
                'Order': self._settings.parent_order,
                'st': str(self._settings.parent_page_size),
                'Type': self._settings.parent_type,
                'ZSType': self._settings.parent_zs_type,
            },
            include_credentials=True,
        )

    def list_stock_codes(self, industry_code):
        if not industry_code:
            raise ValueError('Industry code is required.')
        stock_codes: list[str] = []
        seen_codes: set[str] = set()
        seen_pages: set[tuple[str, ...]] = set()
        for page in range(1000):
            payload = self._post({
                **self._common_params(include_credentials=True),
                'Order': self._settings.stock_order,
                'TSZB': self._settings.stock_tszb,
                'a': get_required_setting('KAIPANLA_STOCK_LIST_ACTION'),
                'st': str(self._settings.stock_page_size),
                'c': self._settings.controller,
                'old': self._settings.stock_old,
                'IsZZ': self._settings.stock_is_zz,
                'Index': str(page * self._settings.stock_page_size),
                'Date': self._request_date(),
                'Type': self._settings.stock_type,
                'IsKZZType': self._settings.stock_is_kzz_type,
                'PlateID': industry_code,
            })
            rows = self._rows(payload, 'list')
            if not rows:
                return tuple(stock_codes)
            page_codes = self._map_stock_codes(rows)
            signature = tuple(page_codes)
            if not page_codes or signature in seen_pages:
                raise KaipanlaPayloadError('Kaipanla stock pagination repeated a page.')
            seen_pages.add(signature)
            for stock_code in page_codes:
                if stock_code not in seen_codes:
                    seen_codes.add(stock_code)
                    stock_codes.append(stock_code)
            if len(rows) < self._settings.stock_page_size:
                return tuple(stock_codes)
        raise KaipanlaPayloadError('Kaipanla stock pagination exceeded its safety bound.')

    def _list_industries(self, *, action, response_key, params, include_credentials):
        industries: list[dict[str, str]] = []
        seen_codes: set[str] = set()
        seen_pages: set[tuple[str, ...]] = set()
        for page in range(1000):
            payload = self._post({
                **self._common_params(include_credentials=include_credentials),
                'a': action,
                'c': self._settings.controller,
                'Index': str(page * self._settings.parent_page_size),
                'Date': self._request_date(),
                **params,
            })
            rows = self._rows(payload, response_key)
            if not rows:
                return tuple(industries)
            page_industries = self._map_industries(rows)
            signature = tuple(item['industry_code'] for item in page_industries)
            if not signature or signature in seen_pages:
                raise KaipanlaPayloadError('Kaipanla industry pagination repeated a page.')
            seen_pages.add(signature)
            for industry in page_industries:
                code = industry['industry_code']
                if code not in seen_codes:
                    seen_codes.add(code)
                    industries.append(industry)
            if len(rows) < self._settings.parent_page_size:
                return tuple(industries)
        raise KaipanlaPayloadError('Kaipanla industry pagination exceeded its safety bound.')

    def _common_params(self, *, include_credentials):
        params = {
            'PhoneOSNew': self._settings.phone_os_new,
            'VerSion': self._settings.version,
            'apiv': self._settings.api_version,
        }
        if self._settings.device_id:
            params['DeviceID'] = self._settings.device_id
        if include_credentials and self._settings.user_id:
            params['UserID'] = self._settings.user_id
        if include_credentials and self._settings.token:
            params['Token'] = self._settings.token
        return params

    @staticmethod
    def _map_industries(rows):
        result = []
        for row in rows:
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                raise KaipanlaPayloadError('Kaipanla industry row is invalid.')
            code = str(row[0]).strip()
            name = str(row[1]).strip()
            if not code or not name:
                raise KaipanlaPayloadError('Kaipanla industry row is incomplete.')
            result.append({'industry_code': code, 'industry_name': name})
        return tuple(result)

    @staticmethod
    def _map_stock_codes(rows):
        result = []
        for row in rows:
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                raise KaipanlaPayloadError('Kaipanla stock row is invalid.')
            code = str(row[0]).strip()
            if not re.fullmatch(r'\d{6}', code):
                raise KaipanlaPayloadError('Kaipanla stock row has an invalid code.')
            result.append(code)
        return tuple(result)

    @staticmethod
    def _rows(payload, response_key):
        rows = payload.get(response_key)
        if not isinstance(rows, list):
            raise KaipanlaPayloadError('Kaipanla response list is invalid.')
        return rows

    def _request_date(self):
        """Return the ``Date`` upstream accepts, which is never a non-trading day.

        The history endpoint serves a session's industry-to-stock mapping, and it
        answers ``errcode 1020`` (参数出错) for weekends, holidays and any date
        without a session. Defaulting to today therefore broke every off-session
        run, so the default resolves to the newest served trading day instead.
        ``KAIPANLA_INDUSTRY_DATE`` still overrides it for deliberate backfills.
        """
        if self._request_date_value is None:
            configured = (get_setting('KAIPANLA_INDUSTRY_DATE', '') or '').strip()
            self._request_date_value = configured or latest_trading_date().isoformat()
        return self._request_date_value

    def _post(self, data: dict[str, Any]):
        # 与同花顺客户端同样的口径：重试记 WARNING、放弃记 ERROR、成功只记 DEBUG。
        started_at = perf_counter()
        for attempt in range(self._settings.max_retries + 1):
            if self._settings.request_delay_seconds:
                sleep(self._settings.request_delay_seconds)
            try:
                try:
                    response = self._transport.post(
                        self._settings.endpoint,
                        data=data,
                        headers=request_headers(),
                        timeout=self._settings.timeout_seconds,
                    )
                except requests.RequestException as error:
                    raise KaipanlaUnavailableError(
                        'Kaipanla is temporarily unavailable.'
                    ) from error
                payload = self._parse_response(response)
            except KaipanlaUnavailableError as error:
                if attempt == self._settings.max_retries:
                    log_event(
                        logger,
                        'upstream_failed',
                        level=logging.ERROR,
                        provider='kaipanla',
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
                    provider='kaipanla',
                    attempt=attempt + 1,
                    retry_delay_seconds=self._settings.request_delay_seconds,
                    reason=error,
                )
                continue
            logger.debug(
                '%s provider=kaipanla duration_ms=%s',
                'upstream_ok',
                elapsed_ms(started_at),
            )
            return payload
        raise AssertionError('Bounded Kaipanla request loop unexpectedly ended.')

    @staticmethod
    def _parse_response(response):
        if response.status_code == 429:
            raise KaipanlaRateLimitError('Kaipanla request was throttled.')
        if not 200 <= response.status_code < 300:
            raise KaipanlaUnavailableError('Kaipanla request failed.')
        try:
            payload = response.json()
        except ValueError as error:
            raise KaipanlaPayloadError('Kaipanla returned invalid JSON.') from error
        if not isinstance(payload, dict):
            raise KaipanlaPayloadError('Kaipanla response envelope is invalid.')
        error_code = str(payload.get('errcode', '')).strip()
        if error_code != '0':
            raise KaipanlaUnavailableError(
                'Kaipanla request was rejected'
                + _upstream_error_detail(error_code, payload.get('errmsg'))
                + '.'
            )
        return payload
