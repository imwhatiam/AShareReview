"""Independent inflow/outflow collection with bounded retries."""

from dataclasses import dataclass
from time import sleep

from backend.env import get_required_setting
from eastmoney.services.client import (
    EastmoneyPayloadError,
    EastmoneySectorFundFlowClient,
    EastmoneyUnavailableError,
)
from eastmoney.services.parser import extract_ranking_rows, parse_sector_row


@dataclass(frozen=True)
class EastmoneyDirectionFetchResult:
    direction: str
    rows: tuple[dict, ...]
    succeeded: bool
    error_summary: str = ''

    @property
    def record_count(self) -> int:
        return len(self.rows)


@dataclass(frozen=True)
class EastmoneySectorFundFlowFetchResult:
    rows: tuple[dict, ...]
    inflow: EastmoneyDirectionFetchResult
    outflow: EastmoneyDirectionFetchResult

    @property
    def has_publishable_rows(self) -> bool:
        return bool(self.rows) and (self.inflow.succeeded or self.outflow.succeeded)


class EastmoneySectorFundFlowFetcher:
    """Fetch the two rankings without discarding a successful direction."""

    def __init__(
        self,
        *,
        client=None,
        max_retries=None,
        retry_delay_seconds=None,
        ranking_interval_seconds=None,
        sleep_fn=None,
    ):
        self.client = client or EastmoneySectorFundFlowClient()
        self.max_retries = (
            _non_negative_integer_setting('EASTMONEY_MAX_RETRIES')
            if max_retries is None
            else max_retries
        )
        self.retry_delay_seconds = (
            _non_negative_float_setting('EASTMONEY_REQUEST_DELAY_SECONDS')
            if retry_delay_seconds is None
            else retry_delay_seconds
        )
        self.ranking_interval_seconds = (
            _non_negative_float_setting('EASTMONEY_RANKING_INTERVAL_SECONDS')
            if ranking_interval_seconds is None
            else ranking_interval_seconds
        )
        self.sleep = sleep_fn or sleep

    def fetch(self) -> EastmoneySectorFundFlowFetchResult:
        """Fetch both rankings and merge valid rows by stable sector code."""
        inflow = self._fetch_direction('inflow')
        if self.ranking_interval_seconds:
            self.sleep(self.ranking_interval_seconds)
        outflow = self._fetch_direction('outflow')

        rows_by_code = {row['sector_code']: row for row in inflow.rows}
        rows_by_code.update({row['sector_code']: row for row in outflow.rows})
        return EastmoneySectorFundFlowFetchResult(
            rows=tuple(rows_by_code.values()),
            inflow=inflow,
            outflow=outflow,
        )

    def _fetch_direction(self, direction: str) -> EastmoneyDirectionFetchResult:
        last_error = ''
        for attempt in range(self.max_retries + 1):
            try:
                payload = self.client.fetch_ranking(direction)
            except (EastmoneyUnavailableError, EastmoneyPayloadError) as error:
                last_error = str(error)
                if attempt < self.max_retries and self.retry_delay_seconds:
                    self.sleep(self.retry_delay_seconds)
                continue

            rows = tuple(
                parsed for raw_row in extract_ranking_rows(payload)
                if (parsed := parse_sector_row(raw_row)) is not None
            )
            if rows:
                return EastmoneyDirectionFetchResult(direction, rows, succeeded=True)
            last_error = 'Eastmoney returned no valid sector rows.'
            if attempt < self.max_retries and self.retry_delay_seconds:
                self.sleep(self.retry_delay_seconds)

        return EastmoneyDirectionFetchResult(direction, (), succeeded=False, error_summary=last_error)


def _non_negative_integer_setting(name: str) -> int:
    value = get_required_setting(name)
    try:
        parsed = int(value)
    except ValueError as error:
        raise ValueError(f'{name} must be an integer.') from error
    if parsed < 0:
        raise ValueError(f'{name} must not be negative.')
    return parsed


def _non_negative_float_setting(name: str) -> float:
    value = get_required_setting(name)
    try:
        parsed = float(value)
    except ValueError as error:
        raise ValueError(f'{name} must be numeric.') from error
    if parsed < 0:
        raise ValueError(f'{name} must not be negative.')
    return parsed
