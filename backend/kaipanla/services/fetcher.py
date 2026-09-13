"""Bounded pagination and completeness validation for Kaipanla fund flow."""

import logging
import time
from dataclasses import dataclass
from math import ceil

from backend.env import get_required_setting
from core.logging import ProgressReporter, log_event
from kaipanla.services.client import (
    KaipanlaPayloadError,
    KaipanlaRateLimitError,
    KaipanlaSectorFundFlowClient,
    KaipanlaUnavailableError,
    flow_client_settings,
)
from kaipanla.services.parser import KaipanlaSectorFundFlowRow, parse_sector_row


logger = logging.getLogger(__name__)


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
    # ``error_summary`` 是给人看的句子，机器需要的是"为什么没拿到页"：
    # 'rate_limited' / 'unavailable' / 'payload' 之一，或 None（与上游无关的失败，
    # 例如页数超预算、页内容为空）。读路径用它把失败映射成稳定错误码。
    failure_kind: str | None = None
    # 上游 ``Count`` 声称的总行数。``len(rows)`` 是**去重后能用的行数**，两者之差
    # 就是"丢了什么"，写进采集运行的 missing_record_count（以前那里恒为 0）。
    upstream_record_count: int | None = None
    # 上游给到了行、但解析不出来的条数。以前这些行被静默跳过，快照照样标 complete，
    # 板块可以一整批消失而无人知晓；现在它是个可读的数字。
    invalid_row_count: int = 0


def _failure_kind(error: Exception | None) -> str | None:
    """Classify a terminal page failure for the error-code mapping."""
    if error is None:
        return None
    if isinstance(error, KaipanlaRateLimitError):
        return 'rate_limited'
    if isinstance(error, KaipanlaUnavailableError):
        return 'unavailable'
    if isinstance(error, KaipanlaPayloadError):
        return 'payload'
    return None


def _non_negative_integer(name: str) -> int:
    value = get_required_setting(name)
    try:
        parsed = int(value)
    except ValueError as error:
        raise ValueError(f'{name} must be an integer.') from error
    if parsed < 0:
        raise ValueError(f'{name} must not be negative.')
    return parsed


def _positive_integer(name: str) -> int:
    value = _non_negative_integer(name)
    if value == 0:
        raise ValueError(f'{name} must be positive.')
    return value


@dataclass(frozen=True)
class KaipanlaSectorFundFlowFetchSettings:
    """Pagination policy for one fund-flow collection.

    ``page_size`` and ``retry_delay_seconds`` come from the client settings on
    purpose: the client stamps ``page_size`` into ``st`` and sleeps
    ``request_delay_seconds`` between requests, so the two must agree. The other
    two are read straight from `.env`.
    """

    page_size: int
    max_retries: int
    retry_delay_seconds: float
    max_pages: int


def fetch_settings(client_settings=None) -> KaipanlaSectorFundFlowFetchSettings:
    """Load the four pagination knobs from one place, for every caller.

    Until 2026-09-13 three of them silently switched source when a ``client``
    was injected: ``max_pages`` became a hardcoded **100** while `.env` said 20,
    ``retry_delay_seconds`` became a hardcoded 0.0, and ``page_size`` had no
    fallback at all (``None.page_size``). Injecting a client is about *transport*
    — tests pass a fake session — so it must not move a single default. The only
    way to make that true is to derive all four here, from the same place.
    """
    client_settings = flow_client_settings() if client_settings is None else client_settings
    return KaipanlaSectorFundFlowFetchSettings(
        page_size=client_settings.page_size,
        max_retries=_non_negative_integer('KAIPANLA_MAX_RETRIES'),
        retry_delay_seconds=client_settings.request_delay_seconds,
        max_pages=_positive_integer('KAIPANLA_FLOW_MAX_PAGES'),
    )


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
        sleep_fn=None,
    ):
        settings = flow_client_settings()
        # ``client`` 只决定"用哪条传输"，分页策略一律来自 `settings`（即 .env）。
        # 每个参数都是"显式传就用传进来的，否则用同一份配置"，没有任何一个参数
        # 会因为注入 client 而换成写死的数字。
        self.client = client or KaipanlaSectorFundFlowClient(settings=settings)
        defaults = fetch_settings(settings)
        self.page_size = defaults.page_size if page_size is None else page_size
        self.max_retries = defaults.max_retries if max_retries is None else max_retries
        self.retry_delay_seconds = (
            defaults.retry_delay_seconds if retry_delay_seconds is None else retry_delay_seconds
        )
        self.max_pages = defaults.max_pages if max_pages is None else max_pages
        # 参数名不能叫 `sleep`（名字被遮蔽后只能写 `__import__('time').sleep` 绕开）；
        # 与 `KaipanlaSectorFundFlowClient` 的 `sleep_fn` 命名保持一致。
        self.sleep = sleep_fn or time.sleep
        # 最近一次放弃的页为什么失败；`_incomplete` 把它翻译成 failure_kind。
        self.last_failure_kind: str | None = None

    def fetch(self) -> KaipanlaSectorFundFlowFetchResult:
        rows_by_code = {}
        expected_page_count = 0
        completed_page_count = 0
        source_timestamp = None
        source_trade_date = None
        upstream_record_count = None
        seen_row_count = 0
        invalid_row_count = 0

        first_response = self._fetch_with_retry(0)
        if first_response is None:
            return self._incomplete(
                expected_page_count=0,
                completed_page_count=0,
                failed_page_offsets=(0,),
                source_timestamp=None,
                source_trade_date=None,
                error_summary='The first page failed.',
                failure_kind=self.last_failure_kind,
            )
        source_timestamp, source_trade_date = self._source_metadata(first_response)
        total_count = self._total_count(first_response)
        if total_count is None or total_count <= 0:
            return self._incomplete(
                expected_page_count=0,
                completed_page_count=0,
                failed_page_offsets=(0,),
                source_timestamp=source_timestamp,
                source_trade_date=source_trade_date,
                error_summary='Invalid count.',
            )
        upstream_record_count = total_count
        expected_page_count = ceil(total_count / self.page_size)
        if expected_page_count > self.max_pages:
            return self._incomplete(
                expected_page_count=expected_page_count,
                completed_page_count=0,
                failed_page_offsets=(0,),
                source_timestamp=source_timestamp,
                source_trade_date=source_trade_date,
                error_summary='Page limit exceeded.',
            )

        # 每页一次请求，页数已知：报页码 + 已归集行数，重试等待期间也能看出还在推进。
        progress = ProgressReporter(
            'kaipanla_sector_fund_flow',
            total=expected_page_count,
            page_size=self.page_size,
            source_trade_date=source_trade_date,
        )
        progress.start(action='fetching_pages', total_records=total_count)
        for page_number in range(expected_page_count):
            offset = page_number * self.page_size
            response = first_response if page_number == 0 else self._fetch_with_retry(offset)
            if response is None or not self._is_success_response(response):
                return self._incomplete(
                    expected_page_count=expected_page_count,
                    completed_page_count=completed_page_count,
                    failed_page_offsets=(offset,),
                    source_timestamp=source_timestamp,
                    source_trade_date=source_trade_date,
                    error_summary='A required page failed.',
                    failure_kind=self.last_failure_kind,
                    upstream_record_count=upstream_record_count,
                    invalid_row_count=invalid_row_count,
                )
            items = response.get('list')
            if not isinstance(items, list) or not items:
                return self._incomplete(
                    expected_page_count=expected_page_count,
                    completed_page_count=completed_page_count,
                    failed_page_offsets=(offset,),
                    source_timestamp=source_timestamp,
                    source_trade_date=source_trade_date,
                    error_summary='A required page was empty or malformed.',
                    upstream_record_count=upstream_record_count,
                    invalid_row_count=invalid_row_count,
                )
            is_last_page = page_number == expected_page_count - 1
            if not is_last_page and len(items) < self.page_size:
                return self._incomplete(
                    expected_page_count=expected_page_count,
                    completed_page_count=completed_page_count,
                    failed_page_offsets=(offset,),
                    source_timestamp=source_timestamp,
                    source_trade_date=source_trade_date,
                    error_summary='A required page was shorter than requested.',
                    upstream_record_count=upstream_record_count,
                    invalid_row_count=invalid_row_count,
                )
            for item in items:
                seen_row_count += 1
                row = parse_sector_row(item)
                if row is None:
                    # 坏行不再无声无息：它同时进 log 和结果里的 invalid_row_count，
                    # 最终落到采集运行的 missing_record_count 上。
                    invalid_row_count += 1
                    continue
                rows_by_code[row.sector_code] = row
            completed_page_count += 1
            progress.advance(page=page_number + 1, records=len(rows_by_code))

        progress.report(force=True, action='fetched_pages', records=len(rows_by_code))
        self._report_dropped_rows(
            invalid_row_count=invalid_row_count,
            seen_row_count=seen_row_count,
            kept_row_count=len(rows_by_code),
            upstream_record_count=upstream_record_count,
        )

        if not rows_by_code:
            return self._incomplete(
                expected_page_count=expected_page_count,
                completed_page_count=completed_page_count,
                failed_page_offsets=(),
                source_timestamp=source_timestamp,
                source_trade_date=source_trade_date,
                error_summary='No valid sector rows were returned.',
                upstream_record_count=upstream_record_count,
                invalid_row_count=invalid_row_count,
            )
        return KaipanlaSectorFundFlowFetchResult(
            rows=tuple(rows_by_code.values()),
            is_complete=True,
            expected_page_count=expected_page_count,
            completed_page_count=completed_page_count,
            failed_page_offsets=(),
            source_timestamp=source_timestamp,
            source_trade_date=source_trade_date,
            upstream_record_count=upstream_record_count,
            invalid_row_count=invalid_row_count,
        )

    @staticmethod
    def _report_dropped_rows(
        *, invalid_row_count: int, seen_row_count: int, kept_row_count: int, upstream_record_count
    ) -> None:
        """Log one line per collection when rows did not survive the parse.

        Silent dropping was the whole problem: the snapshot was still published as
        complete, so a whole batch of sectors could vanish with nothing anywhere
        saying so. A warning per collection is loud enough to be noticed in the
        command log and cheap enough to keep for every run.
        """
        if not invalid_row_count:
            return
        log_event(
            logger,
            'rows_dropped',
            level=logging.WARNING,
            invalid_rows=invalid_row_count,
            seen_rows=seen_row_count,
            kept_rows=kept_row_count,
            duplicate_rows=max(seen_row_count - invalid_row_count - kept_row_count, 0),
            upstream_record_count=upstream_record_count,
            reason='upstream rows that cannot be parsed are reported, never silently dropped',
        )

    def _fetch_with_retry(self, offset: int):
        """Fetch one page, or return ``None`` after the retry budget is spent.

        The ``None`` return is deliberate (the fetcher reports incompleteness as
        data), but it used to be the *only* trace of a failed page: a run could
        fail here and end with nothing in the log but "incomplete". Each failed
        attempt is now recorded, and giving up is an ERROR.
        """
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.fetch_page(offset)
            except (KaipanlaUnavailableError, KaipanlaPayloadError) as error:
                last_error = error
                if attempt == self.max_retries:
                    break
                log_event(
                    logger,
                    'page_retry',
                    level=logging.WARNING,
                    offset=offset,
                    attempt=attempt + 1,
                    retry_delay_seconds=self.retry_delay_seconds,
                    reason=error,
                )
                if self.retry_delay_seconds:
                    self.sleep(self.retry_delay_seconds)
                continue
            if self._is_success_response(response):
                return response
            last_error = KaipanlaPayloadError(
                f'Kaipanla returned errcode {response.get("errcode")!r}.'
            )
            if attempt == self.max_retries:
                break
            log_event(
                logger,
                'page_retry',
                level=logging.WARNING,
                offset=offset,
                attempt=attempt + 1,
                retry_delay_seconds=self.retry_delay_seconds,
                reason=last_error,
            )
            if self.retry_delay_seconds:
                self.sleep(self.retry_delay_seconds)
        log_event(
            logger,
            'page_failed',
            level=logging.ERROR,
            offset=offset,
            attempts=self.max_retries + 1,
            error=last_error,
        )
        self.last_failure_kind = _failure_kind(last_error)
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
        *,
        expected_page_count,
        completed_page_count,
        failed_page_offsets,
        source_timestamp,
        source_trade_date,
        error_summary,
        failure_kind=None,
        upstream_record_count=None,
        invalid_row_count=0,
    ):
        """Build the "not publishable" fetch result.

        全部关键字传参是刻意的：此前 7 个调用点都写成
        ``_incomplete(0, 0, (0,), None, None, '...')``，读者必须先回看这个签名才知道
        那两个 ``0`` 与两个 ``None`` 分别是哪几个字段。开头的 ``*`` 让解释器替我们
        挡住位置传参，以后给结果加字段也不会再错位。
        """
        return KaipanlaSectorFundFlowFetchResult(
            rows=(),
            is_complete=False,
            expected_page_count=expected_page_count,
            completed_page_count=completed_page_count,
            failed_page_offsets=failed_page_offsets,
            source_timestamp=source_timestamp,
            source_trade_date=source_trade_date,
            error_summary=error_summary,
            failure_kind=failure_kind,
            upstream_record_count=upstream_record_count,
            invalid_row_count=invalid_row_count,
        )
