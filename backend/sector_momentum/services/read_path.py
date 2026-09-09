"""Cache-first reads and bounded local rebuilds for sector-momentum results."""

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
from sector_momentum.models import SectorMomentumRanking, SectorMomentumResult
from sector_momentum.services.analysis import build_sector_momentum_analysis
from sector_momentum.services.source_versions import (
    CompleteIndustrySnapshotUnavailable,
    get_complete_industry_snapshot_version,
)
from sector_momentum.services.writer import write_sector_momentum_analysis

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


def _result_for_date(business_date: date) -> tuple[SectorMomentumResult | None, bool]:
    daily_price_version, industry_version = _current_source_versions(business_date)
    results = SectorMomentumResult.objects.using('sector_momentum').filter(
        business_date=business_date
    )
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


def _bounded_local_rebuild(business_date: date) -> SectorMomentumResult:
    """Use only already-local public data; this path never synchronizes upstream data."""
    snapshot = get_complete_market_snapshot(business_date)
    if len(snapshot.prices) > _max_local_repair_rows():
        raise CompleteMarketDataUnavailable(
            'The local public snapshot exceeds the web-request rebuild budget.'
        )
    try:
        industry_version = get_complete_industry_snapshot_version()
    except CompleteIndustrySnapshotUnavailable as error:
        raise CompleteMarketDataUnavailable(str(error)) from error
    analysis = build_sector_momentum_analysis(snapshot, industry_version)
    write_result = write_sector_momentum_analysis(
        business_date=business_date,
        analysis=analysis,
    )
    return SectorMomentumResult.objects.using('sector_momentum').get(pk=write_result.result_id)


def _data_version(result: SectorMomentumResult) -> str:
    return f'{result.source_daily_price_version}:{result.source_industry_version}'


def _serialize(result: SectorMomentumResult) -> dict:
    rankings: dict[str, list[dict]] = {
        value: [] for value in SectorMomentumRanking.Metric.values
    }
    for ranking in result.rankings.all().order_by('metric', 'rank'):
        rankings[ranking.metric].append({
            'rank': ranking.rank,
            'industry_code': ranking.industry_code,
            'industry_name': ranking.industry_name,
            'stock_count': ranking.stock_count,
            'average_change_percent': ranking.average_change_percent,
            'industry_turnover': ranking.industry_turnover,
            'market_turnover_ratio': ranking.market_turnover_ratio,
            'score': ranking.score,
            'stocks': ranking.stocks,
        })
    return {
        'trade_date': str(result.business_date),
        'source_daily_price_version': result.source_daily_price_version,
        'source_industry_version': result.source_industry_version,
        'total_market_turnover': result.total_market_turnover,
        'unmapped_stock_count': result.unmapped_stock_count,
        'rankings': rankings,
    }


def _warnings(result: SectorMomentumResult, stale: bool) -> tuple[str, ...]:
    warnings: list[str] = []
    if result.unmapped_stock_count:
        warnings.append(
            f'{result.unmapped_stock_count} 只有效股票未映射到开盘啦父行业。'
        )
    if stale:
        warnings.append('公共行情或开盘啦行业映射已更新，正在展示最近可用的分析结果。')
    return tuple(warnings)


def _read_or_rebuild(
    business_date: date, result: SectorMomentumResult | None, stale: bool
) -> tuple[SectorMomentumResult, str, bool]:
    if result is None or stale:
        try:
            return _bounded_local_rebuild(business_date), 'computed', False
        except CompleteMarketDataUnavailable:
            if result is None:
                raise
    assert result is not None
    return result, 'database', stale


def read_sector_momentum(trade_date: date | None = None) -> ReadResult:
    """Read a result, repairing only from small already-local source snapshots."""
    if trade_date is None:
        result = SectorMomentumResult.objects.using('sector_momentum').order_by(
            '-business_date', '-created_at'
        ).first()
        if result is None:
            trade_date = latest_complete_stock_price_date()
            if trade_date is None:
                raise CompleteMarketDataUnavailable('No complete public daily-price data is available.')
            result, source, stale = _read_or_rebuild(trade_date, None, False)
        else:
            trade_date = result.business_date
            current, stale = _result_for_date(trade_date)
            result, source, stale = _read_or_rebuild(trade_date, current, stale)
    else:
        result, stale = _result_for_date(trade_date)
        result, source, stale = _read_or_rebuild(trade_date, result, stale)

    data_version = _data_version(result)
    cache = default_file_cache()
    key = build_cache_key(
        'sector_momentum', 'result', {'date': str(trade_date)}, data_version
    )
    if cache is not None and source != 'computed':
        cached = cache.get(key, data_version)
        if cached is not None:
            return ReadResult(
                cached, result.business_date, data_version, 'cache', stale,
                _warnings(result, stale),
            )

    data = _serialize(result)
    if cache is not None:
        try:
            cache.set(key, data, data_version)
        except CachePayloadTooLarge:
            pass
    return ReadResult(
        data, result.business_date, data_version, source, stale, _warnings(result, stale)
    )


def read_dates() -> ReadResult:
    result = SectorMomentumResult.objects.using('sector_momentum').order_by(
        '-business_date', '-created_at'
    ).first()
    if result is None:
        raise CompleteMarketDataUnavailable('No sector-momentum analysis result is available.')
    data_version = _data_version(result)
    cache = default_file_cache()
    key = build_cache_key('sector_momentum', 'dates', {}, data_version)
    if cache is not None:
        cached = cache.get(key, data_version)
        if cached is not None:
            return ReadResult(cached, result.business_date, data_version, 'cache')

    data = {
        'dates': [
            str(value)
            for value in SectorMomentumResult.objects.using('sector_momentum').order_by(
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
