"""Configurable single-page Kaipanla sector-fund-flow HTTP client."""

from dataclasses import dataclass
import json
import re
from time import sleep
from typing import Any

import requests
from django.core.exceptions import ImproperlyConfigured

from backend.env import get_required_setting, get_setting


class KaipanlaUnavailableError(RuntimeError):
    """The upstream service did not complete a usable request."""


class KaipanlaPayloadError(RuntimeError):
    """The upstream service returned an invalid payload."""


@dataclass(frozen=True)
class KaipanlaSectorFundFlowClientSettings:
    endpoint: str
    device_id: str
    user_id: str
    token: str
    version: str
    api_version: str
    phone_os_new: str
    timeout_seconds: int
    controller: str
    action: str
    order: str
    ranking_type: str
    zs_type: str
    page_size: int = 80
    request_delay_seconds: float = 0.0


def _positive_integer_setting(name: str, *, minimum: int = 0) -> int:
    value = get_required_setting(name)
    try:
        parsed = int(value)
    except ValueError as error:
        raise ImproperlyConfigured(f'{name} must be an integer.') from error
    if parsed < minimum:
        raise ImproperlyConfigured(f'{name} must be at least {minimum}.')
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


def flow_client_settings() -> KaipanlaSectorFundFlowClientSettings:
    """Read all Kaipanla flow endpoint parameters from the repository .env."""
    page_size = _positive_integer_setting('KAIPANLA_FLOW_PAGE_SIZE', minimum=1)
    if page_size > 80:
        raise ImproperlyConfigured('KAIPANLA_FLOW_PAGE_SIZE must not exceed 80.')
    return KaipanlaSectorFundFlowClientSettings(
        endpoint=get_required_setting('KAIPANLA_API_URL'),
        device_id=get_required_setting('KPL_DEVICE_ID'),
        user_id=get_setting('KPL_USER_ID', '') or '',
        token=get_setting('KPL_TOKEN', '') or '',
        version=get_required_setting('KPL_VERSION'),
        api_version=get_required_setting('KPL_API_VERSION'),
        phone_os_new=get_required_setting('KPL_PHONE_OS_NEW'),
        timeout_seconds=_positive_integer_setting('KAIPANLA_TIMEOUT_SECONDS', minimum=1),
        controller=get_required_setting('KAIPANLA_FLOW_CONTROLLER'),
        action=get_required_setting('KAIPANLA_FLOW_ACTION'),
        order=get_required_setting('KAIPANLA_FLOW_ORDER'),
        ranking_type=get_required_setting('KAIPANLA_FLOW_TYPE'),
        zs_type=get_required_setting('KAIPANLA_FLOW_ZS_TYPE'),
        page_size=page_size,
        request_delay_seconds=_non_negative_float_setting('KAIPANLA_REQUEST_DELAY_SECONDS'),
    )


class KaipanlaSectorFundFlowClient:
    """Issue one `RealRankingInfo` form request and decode its payload."""

    def __init__(self, *, settings=None, transport=None, sleep_fn=None):
        self.settings = settings or flow_client_settings()
        self.transport = transport or requests.Session()
        self.sleep = sleep_fn or sleep

    def fetch_page(self, offset: int) -> dict[str, Any]:
        if offset < 0 or offset % self.settings.page_size:
            raise ValueError('Kaipanla page offset must be a non-negative page boundary.')
        if self.settings.request_delay_seconds:
            self.sleep(self.settings.request_delay_seconds)
        try:
            response = self.transport.post(
                self.settings.endpoint,
                data=self._form_data(offset),
                headers={
                    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                    'User-Agent': get_setting(
                        'KAIPANLA_USER_AGENT',
                        'Dalvik/2.1.0 (Linux; U; Android 12; ALN-AL00 Build/W528JS)',
                    ),
                    'Accept-Encoding': 'gzip',
                    'Connection': 'Keep-Alive',
                },
                timeout=self.settings.timeout_seconds,
            )
        except requests.RequestException as error:
            raise KaipanlaUnavailableError('Kaipanla request could not be completed.') from error
        if not 200 <= response.status_code < 300:
            raise KaipanlaUnavailableError('Kaipanla request returned a non-success status.')
        return self._decode_payload(response.text)

    def _form_data(self, offset: int) -> dict[str, str]:
        data = {
            'Order': self.settings.order,
            'a': self.settings.action,
            'c': self.settings.controller,
            'st': str(self.settings.page_size),
            'PhoneOSNew': self.settings.phone_os_new,
            'VerSion': self.settings.version,
            'apiv': self.settings.api_version,
            'Type': self.settings.ranking_type,
            'ZSType': self.settings.zs_type,
            'Index': str(offset),
            'DeviceID': self.settings.device_id,
        }
        if self.settings.user_id:
            data['UserID'] = self.settings.user_id
        if self.settings.token:
            data['Token'] = self.settings.token
        return data

    @staticmethod
    def _decode_payload(text: str) -> dict[str, Any]:
        try:
            decoded = text.encode('utf-8').decode('raw_unicode_escape')
            cleaned = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', decoded)
            payload = json.loads(cleaned)
        except (UnicodeError, ValueError, TypeError) as error:
            raise KaipanlaPayloadError('Kaipanla returned invalid JSON.') from error
        if not isinstance(payload, dict):
            raise KaipanlaPayloadError('Kaipanla response envelope is invalid.')
        return payload
