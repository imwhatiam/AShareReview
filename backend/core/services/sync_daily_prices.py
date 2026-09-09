"""One-time initialization and daily synchronization for public A-share prices."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

from django.db import transaction
from django.utils import timezone

from core.integrations.hithink.client import HithinkClient
from core.integrations.hithink.contracts import HithinkPriceBar
from core.models import DailyPrice, DataVersion, Stock, TradingDay
from core.services.calendar import latest_eligible_trading_day
from core.services.market_data import STOCK_DAILY_PRICES_DATASET
from core.services.publication import (
    PublicationRun,
    begin_publication,
    finish_publication,
)
from core.services.run_status import mark_failed


_CHANGE_PERCENT_PRECISION = Decimal('0.000001')


@dataclass(frozen=True)
class DailyPriceSyncResult:
    trading_day_count: int
    record_count: int
    dry_run: bool


def _one_year_before(value: date) -> date:
    try:
        return value.replace(year=value.year - 1)
    except ValueError:
        return value.replace(year=value.year - 1, day=28)


def _active_stocks() -> tuple[Stock, ...]:
    stocks = tuple(Stock.objects.filter(is_active=True).order_by('stock_code'))
    if not stocks:
        raise ValueError('Stock master has no active A-share stocks.')
    return stocks


def _trading_days_between(start_date: date, end_date: date) -> tuple[date, ...]:
    trading_days = tuple(
        TradingDay.objects.filter(
            trade_date__gte=start_date,
            trade_date__lte=end_date,
        )
        .order_by('trade_date')
        .values_list('trade_date', flat=True)
    )
    if not trading_days:
        raise ValueError('No trading days are available for the requested range.')
    return trading_days


def _validate_bars(
    bars: tuple[HithinkPriceBar, ...], trading_days: tuple[date, ...]
) -> dict[date, HithinkPriceBar]:
    allowed_dates = set(trading_days)
    by_date = {}
    for bar in bars:
        if bar.trade_date not in allowed_dates:
            raise ValueError('Historical price data contains a date outside the requested range.')
        if bar.trade_date in by_date:
            raise ValueError('Historical price data contains duplicate trading dates.')
        by_date[bar.trade_date] = bar
    return by_date


def _has_valid_trade(bar: HithinkPriceBar | None) -> bool:
    return bar is not None and all(
        value is not None
        for value in (
            bar.open_price,
            bar.high_price,
            bar.low_price,
            bar.close_price,
            bar.volume,
            bar.turnover,
        )
    )


def _validate_market_coverage(
    bars_by_stock: dict[int, tuple[HithinkPriceBar, ...]],
    trading_days: tuple[date, ...],
) -> None:
    for trading_day in trading_days:
        if not any(
            _has_valid_trade(bar)
            for bars in bars_by_stock.values()
            for bar in bars
            if bar.trade_date == trading_day
        ):
            raise ValueError(
                f'Historical price data contains no valid trades for {trading_day.isoformat()}.'
            )


def _build_daily_prices(
    *,
    stock: Stock,
    bars: tuple[HithinkPriceBar, ...],
    trading_days: tuple[date, ...],
    source_batch_id: str,
    versions_by_date: dict[date, str],
    previous_close: Decimal | None = None,
) -> tuple[DailyPrice, ...]:
    bars_by_date = _validate_bars(bars, trading_days)
    records = []
    for trade_date in trading_days:
        bar = bars_by_date.get(trade_date)
        has_valid_trade = _has_valid_trade(bar)
        change_percent = None
        if has_valid_trade and previous_close not in (None, Decimal('0')):
            change_percent = (
                (bar.close_price - previous_close) / previous_close * Decimal('100')
            ).quantize(_CHANGE_PERCENT_PRECISION, rounding=ROUND_HALF_UP)
        records.append(
            DailyPrice(
                stock=stock,
                trade_date=trade_date,
                pre_close=previous_close if has_valid_trade else None,
                open_price=bar.open_price if bar else None,
                high_price=bar.high_price if bar else None,
                low_price=bar.low_price if bar else None,
                close_price=bar.close_price if bar else None,
                change_percent=change_percent,
                volume=bar.volume if bar else None,
                turnover=bar.turnover if bar else None,
                has_valid_trade=has_valid_trade,
                source_batch_id=source_batch_id,
                source_data_version=versions_by_date[trade_date],
            )
        )
        if has_valid_trade:
            previous_close = bar.close_price
    return tuple(records)


def _previous_valid_close(stock: Stock, before_date: date) -> Decimal | None:
    record = (
        DailyPrice.objects.filter(
            stock=stock,
            trade_date__lt=before_date,
            has_valid_trade=True,
            close_price__isnull=False,
        )
        .order_by('-trade_date')
        .first()
    )
    return record.close_price if record is not None else None


def _begin_runs(trading_days: tuple[date, ...], expected_record_count: int):
    runs = tuple(
        begin_publication(
            'core',
            STOCK_DAILY_PRICES_DATASET,
            trading_day,
            expected_record_count,
        )
        for trading_day in trading_days
    )
    for run in runs:
        DataVersion.objects.filter(version=run.version).update(
            coverage_start_date=run.business_date,
            coverage_end_date=run.business_date,
        )
    return runs


def _upsert(records: tuple[DailyPrice, ...]) -> None:
    DailyPrice.objects.bulk_create(
        records,
        batch_size=500,
        update_conflicts=True,
        update_fields=[
            'pre_close',
            'open_price',
            'high_price',
            'low_price',
            'close_price',
            'change_percent',
            'volume',
            'turnover',
            'has_valid_trade',
            'source_batch_id',
            'source_data_version',
        ],
        unique_fields=['stock', 'trade_date'],
    )


def _complete_runs(runs: tuple[PublicationRun, ...], actual_record_count: int) -> None:
    for run in runs:
        finish_publication(run, actual_record_count, 0)


def _fail_runs(runs: tuple[PublicationRun, ...], error: Exception) -> None:
    running_runs = tuple(
        run
        for run in runs
        if DataVersion.objects.filter(
            version=run.version,
            status=DataVersion.Status.RUNNING,
        ).exists()
    )
    if not running_runs:
        return
    DataVersion.objects.filter(
        version__in=[run.version for run in running_runs],
        status=DataVersion.Status.RUNNING,
    ).update(
        status=DataVersion.Status.FAILED,
        finished_at=timezone.now(),
        error_summary=str(error)[:1000],
    )
    latest_run = running_runs[-1]
    mark_failed(
        latest_run.module_id,
        latest_run.dataset_key,
        latest_run.business_date,
        str(error),
    )


def initialize_stock_daily_prices(*, years: int = 1, dry_run: bool = False):
    if years != 1:
        raise ValueError('Only a one-year initial daily-price import is supported.')
    if DailyPrice.objects.exists():
        raise ValueError('Daily prices already exist; initialization may only run once.')

    end_date = latest_eligible_trading_day()
    if end_date is None:
        raise ValueError('No eligible trading day is available for initialization.')
    trading_days = _trading_days_between(_one_year_before(end_date), end_date)
    stocks = _active_stocks()
    client = HithinkClient()
    source_batch_id = uuid4().hex
    runs: tuple[PublicationRun, ...] = ()
    if not dry_run:
        runs = _begin_runs(trading_days, len(stocks))
    try:
        bars_by_stock = {}
        for stock in stocks:
            bars = client.get_historical_prices(
                stock.thscode,
                start_date=trading_days[0],
                end_date=trading_days[-1],
            )
            _validate_bars(bars, trading_days)
            bars_by_stock[stock.pk] = bars
        _validate_market_coverage(bars_by_stock, trading_days)

        if dry_run:
            return DailyPriceSyncResult(
                len(trading_days),
                len(stocks) * len(trading_days),
                True,
            )

        versions_by_date = {run.business_date: run.version for run in runs}
        records = []
        for stock in stocks:
            records.extend(
                _build_daily_prices(
                    stock=stock,
                    bars=bars_by_stock[stock.pk],
                    trading_days=trading_days,
                    source_batch_id=source_batch_id,
                    versions_by_date=versions_by_date,
                )
            )
        with transaction.atomic():
            _upsert(tuple(records))
            _complete_runs(runs, len(stocks))
    except Exception as error:
        _fail_runs(runs, error)
        raise

    return DailyPriceSyncResult(len(trading_days), len(records), False)


def sync_stock_daily_prices(*, trade_date: date, dry_run: bool = False):
    if not TradingDay.objects.filter(trade_date=trade_date).exists():
        raise ValueError('The requested date is not in the trading calendar.')
    stocks = _active_stocks()
    client = HithinkClient()
    source_batch_id = uuid4().hex
    runs: tuple[PublicationRun, ...] = ()
    if not dry_run:
        runs = _begin_runs((trade_date,), len(stocks))
    try:
        price_inputs = tuple(
            (
                stock,
                client.get_historical_prices(
                    stock.thscode,
                    start_date=trade_date,
                    end_date=trade_date,
                ),
                _previous_valid_close(stock, trade_date),
            )
            for stock in stocks
        )
        bars_by_stock = {}
        for stock, bars, _ in price_inputs:
            _validate_bars(bars, (trade_date,))
            bars_by_stock[stock.pk] = bars
        _validate_market_coverage(bars_by_stock, (trade_date,))

        if dry_run:
            return DailyPriceSyncResult(1, len(stocks), True)

        versions_by_date = {trade_date: runs[0].version}
        records = tuple(
            record
            for stock, bars, previous_close in price_inputs
            for record in _build_daily_prices(
                stock=stock,
                bars=bars,
                trading_days=(trade_date,),
                source_batch_id=source_batch_id,
                versions_by_date=versions_by_date,
                previous_close=previous_close,
            )
        )
        with transaction.atomic():
            _upsert(records)
            _complete_runs(runs, len(stocks))
    except Exception as error:
        _fail_runs(runs, error)
        raise
    return DailyPriceSyncResult(1, len(records), False)
