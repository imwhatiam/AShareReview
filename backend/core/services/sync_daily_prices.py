"""Initialization, weekly revision and intraday refresh for public A-share prices.

Three write paths share this dataset, all of them keyed by
``(stock, trade_date)`` and all of them comparing business values before writing:

- :func:`refresh_intraday_daily_prices` — the *only* scheduled writer. One paged
  whole-market snapshot request refreshes "today" every half hour.
- :func:`initialize_stock_daily_prices` — the weekly full-window revision. It
  walks the year of per-stock history, which is also what repairs anything the
  snapshot could not express (a re-listing stock's previous close, a day that was
  never written).
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from uuid import uuid4

from django.core.exceptions import ImproperlyConfigured
from django.db import transaction

from backend.env import get_setting
from core.integrations.hithink.client import HithinkClient
from core.integrations.hithink.contracts import HithinkPriceBar, HithinkQuoteSnapshot
from core.logging import ProgressReporter, log_command_progress
from core.models import DailyPrice, Stock
from core.services import calendar as trading_calendar
from core.services.calendar import latest_eligible_trading_day


_CHANGE_PERCENT_PRECISION = Decimal('0.000001')
# 比对只看业务字段：source_batch_id 每次运行都不同，把它算进差异会让每次重跑都
# 判定为“全部有变化”。
_COMPARED_PRICE_FIELDS = (
    'pre_close',
    'open_price',
    'high_price',
    'low_price',
    'close_price',
    'change_percent',
    'volume',
    'turnover',
    'has_valid_trade',
)
_PRICE_LOOKUP_BATCH_SIZE = 200


@dataclass(frozen=True)
class DailyPriceSyncResult:
    trading_day_count: int
    record_count: int
    dry_run: bool
    changed_record_count: int = 0
    unchanged_record_count: int = 0
    updated_trading_day_count: int = 0
    is_up_to_date: bool = False
    is_initial_import: bool = False


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
    trading_days = trading_calendar.trading_days_between(start_date, end_date)
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
            )
        )
        if has_valid_trade:
            previous_close = bar.close_price
    return tuple(records)


def _stored_price_values(
    stock_ids: list[int], trading_days: tuple[date, ...]
) -> dict[tuple[int, date], tuple]:
    """Index the stored business values by ``(stock_id, trade_date)``.

    Batching keeps a five-thousand-stock rerun from materialising a million-row
    list at once while still issuing one query per batch.
    """
    index: dict[tuple[int, date], tuple] = {}
    if not stock_ids:
        return index
    for offset in range(0, len(stock_ids), _PRICE_LOOKUP_BATCH_SIZE):
        chunk = stock_ids[offset:offset + _PRICE_LOOKUP_BATCH_SIZE]
        rows = DailyPrice.objects.filter(
            stock_id__in=chunk,
            trade_date__gte=trading_days[0],
            trade_date__lte=trading_days[-1],
        ).values_list('stock_id', 'trade_date', *_COMPARED_PRICE_FIELDS)
        for stock_id, trade_date, *values in rows:
            index[(stock_id, trade_date)] = tuple(values)
    return index


def _record_price_values(record: DailyPrice) -> tuple:
    return tuple(getattr(record, name) for name in _COMPARED_PRICE_FIELDS)


def _split_changed_records(
    records: tuple[DailyPrice, ...], stored: dict[tuple[int, date], tuple]
) -> tuple[tuple[DailyPrice, ...], int, dict[date, int]]:
    """Keep only the rows whose business values differ from what is stored.

    A missing stored row counts as changed, so a rerun also fills gaps left by an
    interrupted import instead of only revising rows that already exist.
    """
    changed: list[DailyPrice] = []
    unchanged_count = 0
    changed_by_date: dict[date, int] = {}
    for record in records:
        if stored.get((record.stock_id, record.trade_date)) == _record_price_values(record):
            unchanged_count += 1
            continue
        changed.append(record)
        changed_by_date[record.trade_date] = changed_by_date.get(record.trade_date, 0) + 1
    return tuple(changed), unchanged_count, changed_by_date


def _upsert(records: tuple[DailyPrice, ...]) -> None:
    """Write the rows that differ; the transaction that wraps this is the publication.

    ``source_batch_id`` is deliberately not an update field: it answers "which
    batch first wrote this row", and restamping an unchanged row would rewrite a
    whole trading day of rows for a value nothing reads.
    """
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
        ],
        unique_fields=['stock', 'trade_date'],
    )


def initialize_stock_daily_prices(*, years: int = 1, dry_run: bool = False):
    """Import the recent year of daily prices, revising whatever already exists.

    The command is safe to rerun: it always fetches the full window and then updates
    only the rows whose business values differ from the stored ones, so it can repair
    a partial import or pick up upstream revisions of historical bars.
    """
    if years != 1:
        raise ValueError('Only a one-year initial daily-price import is supported.')

    end_date = latest_eligible_trading_day()
    trading_days = _trading_days_between(_one_year_before(end_date), end_date)
    stocks = _active_stocks()
    client = HithinkClient()
    source_batch_id = uuid4().hex
    is_initial_import = not DailyPrice.objects.exists()

    bars_by_stock = {}
    # 逐只股票一次远端请求：这是初始化里最长的阶段，按股票报进度。
    fetch_progress = ProgressReporter(
        'stock_daily_prices', total=len(stocks), mode='initialize', phase='fetch'
    )
    fetch_progress.start(action='started', trading_days=len(trading_days))
    for stock in stocks:
        bars = client.get_historical_prices(
            stock.thscode,
            start_date=trading_days[0],
            end_date=trading_days[-1],
        )
        _validate_bars(bars, trading_days)
        bars_by_stock[stock.pk] = bars
        fetch_progress.advance(stock=stock.stock_code, bars=len(bars))
    fetch_progress.report(force=True, action='fetched')
    _validate_market_coverage(bars_by_stock, trading_days)

    build_progress = ProgressReporter('stock_daily_prices', total=len(stocks), phase='build')
    build_progress.start(action='started')
    records: list[DailyPrice] = []
    for stock in stocks:
        records.extend(
            _build_daily_prices(
                stock=stock,
                bars=bars_by_stock[stock.pk],
                trading_days=trading_days,
                source_batch_id=source_batch_id,
            )
        )
        build_progress.advance(stock=stock.stock_code, records=len(records))
    build_progress.report(force=True, action='built')
    built_records = tuple(records)

    log_command_progress('stock_daily_prices', action='comparing', records=len(built_records))
    stored = _stored_price_values([stock.pk for stock in stocks], trading_days)
    changed_records, unchanged_record_count, changed_by_date = _split_changed_records(
        built_records, stored
    )
    changed_dates = tuple(sorted(changed_by_date))
    log_command_progress(
        'stock_daily_prices',
        action='compared',
        records=len(built_records),
        changed=len(changed_records),
        unchanged=unchanged_record_count,
        trading_days=len(changed_dates),
    )

    result = DailyPriceSyncResult(
        trading_day_count=len(trading_days),
        record_count=len(built_records),
        dry_run=dry_run,
        changed_record_count=len(changed_records),
        unchanged_record_count=unchanged_record_count,
        updated_trading_day_count=len(changed_dates),
        is_up_to_date=not changed_dates,
        is_initial_import=is_initial_import,
    )
    if dry_run or not changed_dates:
        # 与上游逐条一致时什么都不写：重写一遍内容相同的行只会无端改动落库时刻。
        return result

    log_command_progress(
        'stock_daily_prices',
        action='writing',
        phase='write',
        records=len(changed_records),
        trading_days=len(changed_dates),
    )
    with transaction.atomic():
        _upsert(changed_records)
    return result


# ---------------------------------------------------------------------------
# 盘中刷新：用全市场实时快照刷新“当天”的公共日行情
# ---------------------------------------------------------------------------

# 分页上限只是防呆：五千多只股票按一页一千只需六页。上游 ``total`` 不可信时
# 也不能让分页循环无限转下去。
_INTRADAY_QUOTE_MAX_PAGES = 50
_INTRADAY_QUOTE_PAGE_SIZE_DEFAULT = 1000
# 快照缺了股票往往意味着分页截断或上游抖动。低于这个覆盖率就整体失败，绝不
# 把半截数据写进“当天” —— 那会让四个页面读到一份“看起来完整”的假行情。
_INTRADAY_QUOTE_MIN_COVERAGE_DEFAULT = '0.95'


@dataclass(frozen=True)
class IntradayQuoteRefreshResult:
    trade_date: date
    quote_count: int
    matched_stock_count: int
    coverage_ratio: Decimal
    changed_record_count: int
    unchanged_record_count: int
    published: bool
    is_up_to_date: bool
    dry_run: bool


def _intraday_quote_page_size() -> int:
    raw = get_setting('INTRADAY_QUOTE_PAGE_SIZE', str(_INTRADAY_QUOTE_PAGE_SIZE_DEFAULT))
    try:
        page_size = int(raw)
    except (TypeError, ValueError) as error:
        raise ImproperlyConfigured('INTRADAY_QUOTE_PAGE_SIZE must be an integer.') from error
    if not 1 <= page_size <= 10000:
        raise ImproperlyConfigured('INTRADAY_QUOTE_PAGE_SIZE must be between 1 and 10000.')
    return page_size


def _intraday_min_coverage_ratio() -> Decimal:
    raw = get_setting(
        'INTRADAY_QUOTE_MIN_COVERAGE_RATIO', _INTRADAY_QUOTE_MIN_COVERAGE_DEFAULT
    )
    try:
        ratio = Decimal(str(raw).strip())
    except (TypeError, InvalidOperation) as error:
        raise ImproperlyConfigured(
            'INTRADAY_QUOTE_MIN_COVERAGE_RATIO must be numeric.'
        ) from error
    if not Decimal('0') < ratio <= Decimal('1'):
        raise ImproperlyConfigured(
            'INTRADAY_QUOTE_MIN_COVERAGE_RATIO must be within (0, 1].'
        )
    return ratio


def _fetch_market_quotes(client, *, page_size: int) -> dict[str, HithinkQuoteSnapshot]:
    """Walk every snapshot page and key the rows by ``thscode``.

    The walk stops on a short or empty page rather than trusting the upstream
    ``total``: a stale total would otherwise keep the loop asking for pages that
    no longer exist. Duplicate codes (the market can move between two page
    requests) collapse onto the later row instead of breaking the unique key.
    """
    quotes: dict[str, HithinkQuoteSnapshot] = {}
    offset = 0
    for _ in range(_INTRADAY_QUOTE_MAX_PAGES):
        page, _total = client.list_market_quotes(limit=page_size, offset=offset)
        if not page:
            break
        for quote in page:
            quotes[quote.thscode] = quote
        if len(page) < page_size:
            break
        offset += page_size
    else:
        raise ValueError('The intraday quote snapshot exceeded the page limit.')
    return quotes


def _quote_has_valid_trade(quote: HithinkQuoteSnapshot) -> bool:
    """A suspended stock arrives with ``last_price: null`` and zero volume.

    Every price is stored as ``None`` in that case: writing the upstream zeros
    instead would satisfy the "all fields present" check and record a fake
    trade.
    """
    return all(
        value is not None
        for value in (
            quote.last_price,
            quote.open_price,
            quote.high_price,
            quote.low_price,
            quote.volume,
            quote.turnover,
        )
    )


def _previous_closes(trade_date: date) -> dict[int, Decimal]:
    """Index the previous trading day's closes by stock id.

    Deliberately not filtered by stock id: a five-thousand-value ``IN`` list
    runs into SQLite's bind-parameter limit, while one full day of closes is a
    single small query.

    These are the *stored* closes, so they match the pipeline's convention (the
    previous close comes from the forward-adjusted series we already hold, not
    from the snapshot's unadjusted ``prev_price``). On an ex-dividend day the
    upstream ``price_change_ratio_pct`` is computed against the raw previous
    close and is therefore wrong for our series.
    """
    previous_day = trading_calendar.previous_trading_day(trade_date)
    return dict(
        DailyPrice.objects.filter(
            trade_date=previous_day,
            has_valid_trade=True,
            close_price__isnull=False,
        ).values_list('stock_id', 'close_price')
    )


def _build_intraday_records(
    *,
    stocks: tuple[Stock, ...],
    quotes: dict[str, HithinkQuoteSnapshot],
    previous_closes: dict[int, Decimal],
    trade_date: date,
    source_batch_id: str,
) -> tuple[DailyPrice, ...]:
    """Build one day of rows from the live snapshot.

    Stocks missing from the snapshot are skipped rather than zeroed: a missing
    code means "we did not hear about it", which must not be recorded as a
    suspended session. Filling such a gap — and recomputing the previous close of
    a stock that resumes trading after a suspension — stays the job of
    :func:`initialize_stock_daily_prices`, which reads one year of per-stock
    history instead of one instant of the whole market.

    实测（2026-09-15 收盘后对拍两条口径）：四个价格字段与 ``has_valid_trade``
    完全一致；``turnover`` 有约 76% 的行存在 1e-9 量级的浮点差（10 亿级上绝对差
    数十元），历史上由盘后历史同步纠正。**但 ``volume`` / ``turnover`` 对 4 只
    北交所标的（如 920045）反而只有快照是对的**，历史日线比真实成交少 3%~25%，
    所以"历史口径一定更准"不成立；这也正是历史同步命令被撤掉、只保留本路径与
    每周全量校正的原因之一。
    """
    records = []
    for stock in stocks:
        quote = quotes.get(stock.thscode)
        if quote is None:
            continue
        has_valid_trade = _quote_has_valid_trade(quote)
        previous_close = previous_closes.get(stock.pk)
        change_percent = None
        if has_valid_trade and previous_close not in (None, Decimal('0')):
            change_percent = (
                (quote.last_price - previous_close) / previous_close * Decimal('100')
            ).quantize(_CHANGE_PERCENT_PRECISION, rounding=ROUND_HALF_UP)
        records.append(
            DailyPrice(
                stock=stock,
                trade_date=trade_date,
                pre_close=previous_close if has_valid_trade else None,
                open_price=quote.open_price if has_valid_trade else None,
                high_price=quote.high_price if has_valid_trade else None,
                low_price=quote.low_price if has_valid_trade else None,
                close_price=quote.last_price if has_valid_trade else None,
                change_percent=change_percent,
                volume=quote.volume if has_valid_trade else None,
                turnover=quote.turnover if has_valid_trade else None,
                has_valid_trade=has_valid_trade,
                source_batch_id=source_batch_id,
            )
        )
    return tuple(records)


def refresh_intraday_daily_prices(
    *, trade_date: date, client=None, dry_run: bool = False
) -> IntradayQuoteRefreshResult:
    """Refresh one trading day's public prices from the live market snapshot.

    This is the only routine writer of this dataset. It runs every half hour
    during the session (and once more after the close with ``--latest``) so the
    three derived modules can follow "today" while it is still trading. The
    transport is one whole-market page walk — about six requests — instead of one
    request per stock, which is what makes that cadence affordable and what keeps
    a transient upstream rejection from costing the day's data.

    A run that finds nothing new writes nothing, so an unchanged snapshot does
    not touch the day's rows at all.
    """
    if not trading_calendar.is_trading_day(trade_date):
        raise ValueError('The requested date is not a trading day.')
    stocks = _active_stocks()
    source_batch_id = uuid4().hex

    log_command_progress(
        'stock_daily_prices', action='fetching_intraday_quotes', trade_date=trade_date
    )
    quotes = _fetch_market_quotes(
        client or HithinkClient(), page_size=_intraday_quote_page_size()
    )
    matched = tuple(stock for stock in stocks if stock.thscode in quotes)
    coverage_ratio = Decimal(len(matched)) / Decimal(len(stocks))
    minimum_ratio = _intraday_min_coverage_ratio()
    log_command_progress(
        'stock_daily_prices',
        action='fetched_intraday_quotes',
        trade_date=trade_date,
        quotes=len(quotes),
        matched=len(matched),
        coverage=str(coverage_ratio),
    )
    if coverage_ratio < minimum_ratio:
        raise ValueError(
            f'The intraday snapshot covers {coverage_ratio:.4f} of the active market, '
            f'below the required {minimum_ratio}.'
        )

    records = _build_intraday_records(
        stocks=matched,
        quotes=quotes,
        previous_closes=_previous_closes(trade_date),
        trade_date=trade_date,
        source_batch_id=source_batch_id,
    )
    stored = _stored_price_values([stock.pk for stock in matched], (trade_date,))
    changed_records, unchanged_record_count, _ = _split_changed_records(records, stored)
    log_command_progress(
        'stock_daily_prices',
        action='compared',
        trade_date=trade_date,
        records=len(records),
        changed=len(changed_records),
        unchanged=unchanged_record_count,
    )

    result = IntradayQuoteRefreshResult(
        trade_date=trade_date,
        quote_count=len(quotes),
        matched_stock_count=len(matched),
        coverage_ratio=coverage_ratio,
        changed_record_count=len(changed_records),
        unchanged_record_count=unchanged_record_count,
        published=False,
        is_up_to_date=not changed_records,
        dry_run=dry_run,
    )
    if dry_run or not changed_records:
        return result

    log_command_progress(
        'stock_daily_prices',
        action='writing',
        phase='write',
        trade_date=trade_date,
        records=len(changed_records),
    )
    with transaction.atomic():
        _upsert(changed_records)
    return IntradayQuoteRefreshResult(
        trade_date=trade_date,
        quote_count=len(quotes),
        matched_stock_count=len(matched),
        coverage_ratio=coverage_ratio,
        changed_record_count=len(changed_records),
        unchanged_record_count=unchanged_record_count,
        published=True,
        is_up_to_date=False,
        dry_run=False,
    )
