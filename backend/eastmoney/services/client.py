"""HTTP client for the configured Eastmoney sector fund-flow endpoint."""

from dataclasses import dataclass
from time import sleep
from typing import Any

import requests
from django.core.exceptions import ImproperlyConfigured

from backend.env import get_required_setting


class EastmoneyUnavailableError(RuntimeError):
    """The upstream endpoint rejected or could not complete a request."""


class EastmoneyPayloadError(RuntimeError):
    """The upstream endpoint returned a malformed JSON payload."""


@dataclass(frozen=True)
class EastmoneySectorFundFlowClientSettings:
    endpoint: str
    timeout_seconds: int
    request_delay_seconds: float
    ut: str
    page_size: int
    fields: str
    inflow_fs: str
    outflow_fs: str
    inflow_order: str
    outflow_order: str
    np: str
    fltt: str
    invt: str
    fid: str
    stat: str
    page_number: str


def eastmoney_client_settings() -> EastmoneySectorFundFlowClientSettings:
    """Read the approved endpoint and all request parameters from `.env`."""
    return EastmoneySectorFundFlowClientSettings(
        endpoint=get_required_setting('EASTMONEY_API_URL'),
        timeout_seconds=_positive_integer_setting('EASTMONEY_TIMEOUT_SECONDS'),
        request_delay_seconds=_non_negative_float_setting('EASTMONEY_REQUEST_DELAY_SECONDS'),
        ut=get_required_setting('EASTMONEY_UT'),
        page_size=_positive_integer_setting('EASTMONEY_PAGE_SIZE'),
        fields=get_required_setting('EASTMONEY_FIELDS'),
        inflow_fs=get_required_setting('EASTMONEY_INFLOW_FS'),
        outflow_fs=get_required_setting('EASTMONEY_OUTFLOW_FS'),
        inflow_order=get_required_setting('EASTMONEY_INFLOW_ORDER'),
        outflow_order=get_required_setting('EASTMONEY_OUTFLOW_ORDER'),
        np=get_required_setting('EASTMONEY_NP'),
        fltt=get_required_setting('EASTMONEY_FLTT'),
        invt=get_required_setting('EASTMONEY_INVT'),
        fid=get_required_setting('EASTMONEY_FID'),
        stat=get_required_setting('EASTMONEY_STAT'),
        page_number=get_required_setting('EASTMONEY_PAGE_NUMBER'),
    )


class EastmoneySectorFundFlowClient:
    """Issue one configured Eastmoney ranking request at a time."""

    def __init__(self, *, settings=None, transport=None, sleep_fn=None):
        self.settings = settings or eastmoney_client_settings()
        self.transport = transport or requests.Session()
        self.sleep = sleep_fn or sleep

    def fetch_ranking(self, direction: str) -> dict[str, Any]:
        """Return one ranking payload or raise a stable, local error class."""
        if self.settings.request_delay_seconds:
            self.sleep(self.settings.request_delay_seconds)
        try:
            response = self.transport.get(
                self.settings.endpoint,
                params=self._query_params(direction),
                timeout=self.settings.timeout_seconds,
            )
        except requests.RequestException as error:
            raise EastmoneyUnavailableError('Eastmoney request could not be completed.') from error

        if not 200 <= response.status_code < 300:
            raise EastmoneyUnavailableError(
                f'Eastmoney request returned HTTP {response.status_code}.'
            )
        try:
            payload = response.json()
        except ValueError as error:
            raise EastmoneyPayloadError('Eastmoney returned invalid JSON.') from error
        if not isinstance(payload, dict):
            raise EastmoneyPayloadError('Eastmoney response envelope is invalid.')
        return payload

    def _query_params(self, direction: str) -> dict[str, str | int]:
        if direction == 'inflow':
            order = self.settings.inflow_order
            fs = self.settings.inflow_fs
        elif direction == 'outflow':
            order = self.settings.outflow_order
            fs = self.settings.outflow_fs
        else:
            raise ValueError('Eastmoney direction must be inflow or outflow.')
        return {
            'po': order,
            'np': self.settings.np,
            'fltt': self.settings.fltt,
            'invt': self.settings.invt,
            'ut': self.settings.ut,
            'fid': self.settings.fid,
            'fs': fs,
            'stat': self.settings.stat,
            'fields': self.settings.fields,
            'pn': self.settings.page_number,
            'pz': self.settings.page_size,
        }


def _positive_integer_setting(name: str) -> int:
    value = get_required_setting(name)
    try:
        parsed = int(value)
    except ValueError as error:
        raise ImproperlyConfigured(f'{name} must be an integer.') from error
    if parsed <= 0:
        raise ImproperlyConfigured(f'{name} must be positive.')
    return parsed


def _non_negative_float_setting(name: str) -> float:
    value = get_required_setting(name)
    try:
        parsed = float(value)
    except ValueError as error:
        raise ImproperlyConfigured(f'{name} must be numeric.') from error
    if parsed < 0:
        raise ImproperlyConfigured(f'{name} must not be negative.')
    return parsed
