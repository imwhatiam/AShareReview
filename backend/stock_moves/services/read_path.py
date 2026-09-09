"""Cache-first local read and bounded local-rebuild path for stock-move results."""

from dataclasses import dataclass
from datetime import date

from backend.env import get_required_setting
from core.models import DataVersion
from core.services.cache_keys import build_cache_key
from core.services.file_cache import CachePayloadTooLarge, default_file_cache
from core.services.market_data import (
    CompleteMarketDataUnavailable,
    get_complete_market_snapshot,
    latest_complete_stock_price_date,
)
from stock_moves.models import StockMoveItem, StockMoveResult
from stock_moves.services.analysis import build_stock_move_analysis
from stock_moves.services.writer import write_stock_move_analysis


STOCK_DAILY_PRICES_DATASET = 'stock_daily_prices'


@dataclass(frozen=True)
class ReadResult:
    data: dict
    business_date: date
    data_version: str
    source: str
    stale: bool = False
    warnings: tuple[str, ...] = ()


def _max_local_repair_rows() -> int:
    try:
        value = int(get_required_setting('REMOTE_REPAIR_MAX_ROWS'))
    except ValueError as error:
        raise ValueError('REMOTE_REPAIR_MAX_ROWS must be an integer.') from error
    if value < 1:
        raise ValueError('REMOTE_REPAIR_MAX_ROWS must be positive.')
    return value


def _latest_public_version(business_date: date) -> str | None:
    version = DataVersion.objects.filter(
        dataset_key=STOCK_DAILY_PRICES_DATASET,
        business_date=business_date,
        status=DataVersion.Status.COMPLETE,
    ).order_by('-last_success_at', '-started_at').first()
    return version.version if version is not None else None


def _result_for_date(business_date: date) -> tuple[StockMoveResult | None, bool]:
    current_version = _latest_public_version(business_date)
    results = StockMoveResult.objects.using('stock_moves').filter(business_date=business_date)
    if current_version is not None:
        current_result = results.filter(
            source_daily_price_version=current_version
        ).order_by('-created_at').first()
        if current_result is not None:
            return current_result, False
    result = results.order_by('-created_at').first()
    return result, bool(result and current_version and result.source_daily_price_version != current_version)


def _bounded_local_rebuild(business_date: date) -> StockMoveResult:
    """Build from already-local core data only; this path never synchronizes upstream data."""
    snapshot = get_complete_market_snapshot(business_date)
    if len(snapshot.prices) > _max_local_repair_rows():
        raise CompleteMarketDataUnavailable(
            'The local public snapshot exceeds the web-request rebuild budget.'
        )
    analysis = build_stock_move_analysis(snapshot)
    write_result = write_stock_move_analysis(
        business_date=business_date,
        source_daily_price_version=snapshot.data_version.version,
        analysis=analysis,
    )
    return StockMoveResult.objects.using('stock_moves').get(pk=write_result.result_id)


def _serialize(result: StockMoveResult) -> dict:
    groups: dict[str, list[dict]] = {choice: [] for choice in StockMoveItem.Group.values}
    for item in result.items.all().order_by('group', 'rank'):
        groups[item.group].append({
            'rank': item.rank,
            'code': item.stock_code,
            'name': item.stock_name,
            'parent_industries': item.parent_industries,
            'change_percent': item.change_percent,
            'turnover': item.turnover,
        })
    return {
        'trade_date': str(result.business_date),
        'groups': groups,
        'group_counts': {
            StockMoveItem.Group.SSE_RISE: result.sse_rise_count,
            StockMoveItem.Group.SSE_FALL: result.sse_fall_count,
            StockMoveItem.Group.SZSE_RISE: result.szse_rise_count,
            StockMoveItem.Group.SZSE_FALL: result.szse_fall_count,
        },
        'stock_codes': sorted({
            item['code'] for group in groups.values() for item in group
        }),
        'distinct_stock_count': result.distinct_stock_count,
    }


def _warnings(result: StockMoveResult, stale: bool) -> tuple[str, ...]:
    warnings = list(result.warnings)
    if stale:
        warnings.append('公共日行情版本已更新，正在展示最近可用的分析结果。')
    return tuple(dict.fromkeys(warnings))


def read_stock_moves(trade_date: date | None = None) -> ReadResult:
    """Read a derived result from cache or SQLite, optionally repairing from local core data."""
    if trade_date is None:
        result = StockMoveResult.objects.using('stock_moves').order_by(
            '-business_date', '-created_at'
        ).first()
        if result is None:
            trade_date = latest_complete_stock_price_date()
            if trade_date is None:
                raise CompleteMarketDataUnavailable('No complete public daily-price data is available.')
            result = _bounded_local_rebuild(trade_date)
            stale = False
            source = 'computed'
        else:
            trade_date = result.business_date
            current, stale = _result_for_date(trade_date)
            if current is not None:
                result = current
            if stale:
                try:
                    result = _bounded_local_rebuild(trade_date)
                    stale = False
                    source = 'computed'
                except CompleteMarketDataUnavailable:
                    source = 'database'
            else:
                source = 'database'
    else:
        result, stale = _result_for_date(trade_date)
        source = 'database'
        if result is None or stale:
            try:
                result = _bounded_local_rebuild(trade_date)
                stale = False
                source = 'computed'
            except CompleteMarketDataUnavailable:
                if result is None:
                    raise

    data_version = result.source_daily_price_version
    cache = default_file_cache()
    key = build_cache_key(
        'stock_moves', 'result', {'date': str(trade_date)}, data_version
    )
    if cache is not None and source != 'computed':
        cached = cache.get(key, data_version)
        if cached is not None:
            return ReadResult(
                cached,
                result.business_date,
                data_version,
                'cache',
                stale=stale,
                warnings=_warnings(result, stale),
            )

    data = _serialize(result)
    if cache is not None:
        try:
            cache.set(key, data, data_version)
        except CachePayloadTooLarge:
            pass
    return ReadResult(
        data,
        result.business_date,
        data_version,
        source,
        stale=stale,
        warnings=_warnings(result, stale),
    )


def read_dates() -> ReadResult:
    result = StockMoveResult.objects.using('stock_moves').order_by(
        '-business_date', '-created_at'
    ).first()
    if result is None:
        raise CompleteMarketDataUnavailable('No stock-move analysis result is available.')
    data_version = result.source_daily_price_version
    cache = default_file_cache()
    key = build_cache_key('stock_moves', 'dates', {}, data_version)
    if cache is not None:
        cached = cache.get(key, data_version)
        if cached is not None:
            return ReadResult(cached, result.business_date, data_version, 'cache')

    data = {
        'dates': [
            str(value)
            for value in StockMoveResult.objects.using('stock_moves').order_by(
                '-business_date'
            ).values_list('business_date', flat=True).distinct()
        ]
    }
    if cache is not None:
        try:
            cache.set(key, data, data_version)
        except CachePayloadTooLarge:
            pass
    return ReadResult(data, result.business_date, data_version, 'database')
