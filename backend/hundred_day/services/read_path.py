"""Cache-first reads and bounded local rebuilds for hundred-day results."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from backend.env import get_required_setting
from core.models import DataVersion
from core.services.cache_keys import build_cache_key
from core.services.file_cache import CachePayloadTooLarge, default_file_cache
from core.services.market_data import (
    STOCK_DAILY_PRICES_DATASET,
    CompleteMarketDataUnavailable,
    latest_complete_stock_price_date,
)
from hundred_day.models import HundredDayResult
from hundred_day.services.analysis import (
    InsufficientHundredDayHistory,
    build_hundred_day_analysis,
)
from hundred_day.services.source_data import load_hundred_day_source_data
from hundred_day.services.source_versions import (
    CompleteIndustrySnapshotUnavailable,
    get_complete_industry_snapshot_version,
)
from hundred_day.services.writer import write_hundred_day_analysis


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


def _latest_daily_price_version(business_date: date) -> str | None:
    version = DataVersion.objects.filter(
        dataset_key=STOCK_DAILY_PRICES_DATASET,
        business_date=business_date,
        status=DataVersion.Status.COMPLETE,
    ).order_by('-last_success_at', '-started_at').first()
    return version.version if version is not None else None


def _current_source_versions(business_date: date) -> tuple[str | None, str | None]:
    daily_price_version = _latest_daily_price_version(business_date)
    try:
        industry_version = get_complete_industry_snapshot_version()
    except CompleteIndustrySnapshotUnavailable:
        industry_version = None
    return daily_price_version, industry_version


def _result_for_date(business_date: date) -> tuple[HundredDayResult | None, bool]:
    daily_price_version, industry_version = _current_source_versions(business_date)
    results = HundredDayResult.objects.using('hundred_day').filter(business_date=business_date)
    if daily_price_version is not None and industry_version is not None:
        result = results.filter(
            source_daily_price_version=daily_price_version,
            source_industry_version=industry_version,
        ).order_by('-created_at').first()
        if result is not None:
            return result, False

    result = results.order_by('-created_at').first()
    stale = bool(result and (
        (daily_price_version is not None and result.source_daily_price_version != daily_price_version)
        or (industry_version is not None and result.source_industry_version != industry_version)
    ))
    return result, stale


def _source_row_count(source) -> int:
    return sum(len(closes) for closes in source.close_prices_by_stock.values())


def _bounded_local_rebuild(business_date: date) -> HundredDayResult:
    """Rebuild from already-local rows only; this function never contacts upstream APIs."""
    source = load_hundred_day_source_data(business_date)
    if _source_row_count(source) > _max_local_repair_rows():
        raise CompleteMarketDataUnavailable(
            'The local public history exceeds the web-request rebuild budget.'
        )
    try:
        industry_version = get_complete_industry_snapshot_version()
    except CompleteIndustrySnapshotUnavailable as error:
        raise CompleteMarketDataUnavailable(str(error)) from error
    analysis = build_hundred_day_analysis(source, source_industry_version=industry_version)
    write_result = write_hundred_day_analysis(analysis=analysis)
    return HundredDayResult.objects.using('hundred_day').get(pk=write_result.result_id)


def _data_version(result: HundredDayResult) -> str:
    return f'{result.source_daily_price_version}:{result.source_industry_version}'


def _ratio(count: int, total: int) -> str | None:
    return str(Decimal(count) / Decimal(total)) if total else None


def _serialize(result: HundredDayResult) -> dict:
    return {
        'trade_date': str(result.business_date),
        'totals': {
            'valid_stock_count': result.valid_stock_count,
            'new_high_count': result.new_high_count,
            'new_low_count': result.new_low_count,
            'new_high_ratio': _ratio(result.new_high_count, result.valid_stock_count),
            'new_low_ratio': _ratio(result.new_low_count, result.valid_stock_count),
        },
        'industry_summaries': [
            {
                'industry_code': summary.industry_code,
                'industry_name': summary.industry_name,
                'stock_count': summary.stock_count,
                'new_high_count': summary.new_high_count,
                'new_low_count': summary.new_low_count,
                'new_high_stocks': summary.new_high_stocks,
                'new_low_stocks': summary.new_low_stocks,
            }
            for summary in result.industry_summaries.all().order_by('industry_code')
        ],
        'stock_flags': [
            {
                'code': flag.stock_code,
                'name': flag.stock_name,
                'parent_industries': flag.parent_industries,
                'is_new_high': flag.is_new_high,
                'is_new_low': flag.is_new_low,
            }
            for flag in result.stock_flags.all().order_by('stock_code')
        ],
        'trend': [
            {
                'trade_date': str(point.trade_date),
                'valid_stock_count': point.valid_stock_count,
                'new_high_count': point.new_high_count,
                'new_low_count': point.new_low_count,
                'new_high_ratio': str(point.new_high_ratio) if point.new_high_ratio is not None else None,
                'new_low_ratio': str(point.new_low_ratio) if point.new_low_ratio is not None else None,
            }
            for point in result.trend_points.all().order_by('trade_date')
        ],
    }


def _warnings(stale: bool) -> tuple[str, ...]:
    return (
        ('公共日行情或行业映射版本已更新，正在展示最近可用的百日分析结果。',)
        if stale else ()
    )


def read_hundred_day(trade_date: date | None = None) -> ReadResult:
    """Read cache, SQLite or an explicitly bounded local rebuild, in that order."""
    if trade_date is None:
        result = HundredDayResult.objects.using('hundred_day').order_by(
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
                except (CompleteMarketDataUnavailable, InsufficientHundredDayHistory):
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
            except (CompleteMarketDataUnavailable, InsufficientHundredDayHistory):
                if result is None:
                    raise

    data_version = _data_version(result)
    cache = default_file_cache()
    key = build_cache_key('hundred_day', 'result', {'date': str(trade_date)}, data_version)
    if cache is not None and source != 'computed':
        cached = cache.get(key, data_version)
        if cached is not None:
            return ReadResult(
                cached, result.business_date, data_version, 'cache', stale, _warnings(stale)
            )

    data = _serialize(result)
    if cache is not None:
        try:
            cache.set(key, data, data_version)
        except CachePayloadTooLarge:
            pass
    return ReadResult(data, result.business_date, data_version, source, stale, _warnings(stale))


def read_dates() -> ReadResult:
    result = HundredDayResult.objects.using('hundred_day').order_by(
        '-business_date', '-created_at'
    ).first()
    if result is None:
        raise CompleteMarketDataUnavailable('No hundred-day analysis result is available.')
    data_version = _data_version(result)
    cache = default_file_cache()
    key = build_cache_key('hundred_day', 'dates', {}, data_version)
    if cache is not None:
        cached = cache.get(key, data_version)
        if cached is not None:
            return ReadResult(cached, result.business_date, data_version, 'cache')
    data = {
        'dates': [
            str(value)
            for value in HundredDayResult.objects.using('hundred_day').order_by(
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
