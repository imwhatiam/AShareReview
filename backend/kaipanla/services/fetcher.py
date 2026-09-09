"""Bounded pagination and completeness validation for Kaipanla fund flow."""

from dataclasses import dataclass
from math import ceil
from time import sleep

from backend.env import get_required_setting
from kaipanla.services.client import (
    KaipanlaPayloadError,
    KaipanlaSectorFundFlowClient,
    KaipanlaUnavailableError,
    flow_client_settings,
)
from kaipanla.services.parser import KaipanlaSectorFundFlowRow, parse_sector_row


@dataclass(frozen=True)
class KaipanlaSectorFundFlowFetchResult:
    rows: tuple[KaipanlaSectorFundFlowRow, ...]
    is_complete: bool
    expected_page_count: int
    completed_page_count: int
    failed_page_offsets: tuple[int, ...]
    source_timestamp: object | None
    source_trade_date: str | None
    error_summary: str = ''


class KaipanlaSectorFundFlowFetcher:
    """Fetch every required page serially; incomplete pages are not publishable."""

    def __init__(
        self,
        *,
        client=None,
        page_size: int | None = None,
        max_retries: int | None = None,
        retry_delay_seconds: float | None = None,
        max_pages: int | None = None,
        sleep=None,
    ):
        settings = flow_client_settings() if client is None else None
        self.client = client or KaipanlaSectorFundFlowClient(settings=settings)
        self.page_size = page_size or settings.page_size
        self.max_retries = (
            max_retries if max_retries is not None else self._non_negative_integer('KAIPANLA_MAX_RETRIES')
        )
        self.retry_delay_seconds = (
            retry_delay_seconds
            if retry_delay_seconds is not None
            else (
                float(get_required_setting('KAIPANLA_REQUEST_DELAY_SECONDS'))
                if client is None
                else 0.0
            )
        )
        self.max_pages = (
            max_pages
            if max_pages is not None
            else (self._positive_integer('KAIPANLA_FLOW_MAX_PAGES') if client is None else 100)
        )
        self.sleep = sleep or __import__('time').sleep

    def fetch(self) -> KaipanlaSectorFundFlowFetchResult:
        rows_by_code = {}
        expected_page_count = 0
        completed_page_count = 0
        source_timestamp = None
        source_trade_date = None

        first_response = self._fetch_with_retry(0)
        if first_response is None:
            return self._incomplete(0, 0, (0,), None, None, 'The first page failed.')
        source_timestamp, source_trade_date = self._source_metadata(first_response)
        total_count = self._total_count(first_response)
        if total_count is None or total_count <= 0:
            return self._incomplete(0, 0, (0,), source_timestamp, source_trade_date, 'Invalid count.')
        expected_page_count = ceil(total_count / self.page_size)
        if expected_page_count > self.max_pages:
            return self._incomplete(
                expected_page_count, 0, (0,), source_timestamp, source_trade_date, 'Page limit exceeded.'
            )

        for page_number in range(expected_page_count):
            offset = page_number * self.page_size
            response = first_response if page_number == 0 else self._fetch_with_retry(offset)
            if response is None or not self._is_success_response(response):
                return self._incomplete(
                    expected_page_count,
                    completed_page_count,
                    (offset,),
                    source_timestamp,
                    source_trade_date,
                    'A required page failed.',
                )
            items = response.get('list')
            if not isinstance(items, list) or not items:
                return self._incomplete(
                    expected_page_count,
                    completed_page_count,
                    (offset,),
                    source_timestamp,
                    source_trade_date,
                    'A required page was empty or malformed.',
                )
            is_last_page = page_number == expected_page_count - 1
            if not is_last_page and len(items) < self.page_size:
                return self._incomplete(
                    expected_page_count,
                    completed_page_count,
                    (offset,),
                    source_timestamp,
                    source_trade_date,
                    'A required page was shorter than requested.',
                )
            for item in items:
                row = parse_sector_row(item)
                if row is not None:
                    rows_by_code[row.sector_code] = row
            completed_page_count += 1

        if not rows_by_code:
            return self._incomplete(
                expected_page_count,
                completed_page_count,
                (),
                source_timestamp,
                source_trade_date,
                'No valid sector rows were returned.',
            )
        return KaipanlaSectorFundFlowFetchResult(
            rows=tuple(rows_by_code.values()),
            is_complete=True,
            expected_page_count=expected_page_count,
            completed_page_count=completed_page_count,
            failed_page_offsets=(),
            source_timestamp=source_timestamp,
            source_trade_date=source_trade_date,
        )

    def _fetch_with_retry(self, offset: int):
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.fetch_page(offset)
            except (KaipanlaUnavailableError, KaipanlaPayloadError):
                if attempt == self.max_retries:
                    return None
                if self.retry_delay_seconds:
                    self.sleep(self.retry_delay_seconds)
                continue
            if self._is_success_response(response):
                return response
            if attempt == self.max_retries:
                return None
            if self.retry_delay_seconds:
                self.sleep(self.retry_delay_seconds)
        return None

    @staticmethod
    def _is_success_response(response) -> bool:
        return isinstance(response, dict) and str(response.get('errcode', '')) == '0'

    @staticmethod
    def _source_metadata(response):
        days = response.get('Day')
        source_trade_date = str(days[0]) if isinstance(days, list) and days else None
        return response.get('Time'), source_trade_date

    @staticmethod
    def _total_count(response) -> int | None:
        try:
            count = int(response.get('Count'))
        except (TypeError, ValueError):
            return None
        return count if count >= 0 else None

    @staticmethod
    def _incomplete(
        expected_page_count,
        completed_page_count,
        failed_page_offsets,
        source_timestamp,
        source_trade_date,
        error_summary,
    ):
        return KaipanlaSectorFundFlowFetchResult(
            rows=(),
            is_complete=False,
            expected_page_count=expected_page_count,
            completed_page_count=completed_page_count,
            failed_page_offsets=failed_page_offsets,
            source_timestamp=source_timestamp,
            source_trade_date=source_trade_date,
            error_summary=error_summary,
        )

    @staticmethod
    def _non_negative_integer(name: str) -> int:
        value = get_required_setting(name)
        try:
            parsed = int(value)
        except ValueError as error:
            raise ValueError(f'{name} must be an integer.') from error
        if parsed < 0:
            raise ValueError(f'{name} must not be negative.')
        return parsed

    @staticmethod
    def _positive_integer(name: str) -> int:
        value = KaipanlaSectorFundFlowFetcher._non_negative_integer(name)
        if value == 0:
            raise ValueError(f'{name} must be positive.')
        return value
