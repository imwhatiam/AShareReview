"""Cache-first reads and on-demand local generation for sector-momentum results.

The cache/version/fallback sequence itself lives in ``core.services.read_path``;
this module only declares what is genuinely sector-momentum's: how to generate a
day, how to serialize it, and what to warn about.
"""

from datetime import date

from core.services.file_cache import default_file_cache
from core.services.locking import DatasetBusy, DatasetLocked, dataset_lock
from core.services.market_data import (
    CompleteMarketDataUnavailable,
    get_complete_market_snapshot,
    latest_complete_stock_price_date,
)
from core.services.read_path import ReadPath, ReadResult  # noqa: F401
from core.services.read_path import read as _read
from core.services.read_path import read_dates as _read_dates
from sector_momentum.models import SectorMomentumRanking, SectorMomentumResult
from sector_momentum.services.analysis import build_sector_momentum_analysis
from sector_momentum.services.source_versions import (
    CompleteIndustrySnapshotUnavailable,
    get_complete_industry_snapshot_version,
)
from sector_momentum.services.writer import write_sector_momentum_analysis

MODULE_ID = 'sector_momentum'
DATASET_KEY = 'sector_momentum'


def _local_generate(business_date: date) -> SectorMomentumResult:
    """Generate one trading day's rankings from already-local core data only.

    This path never synchronizes upstream data: it is a local computation over a
    single day of prices, so there is no row budget to enforce. The dataset lock
    keeps a concurrent request or a running ``build_sector_momentum`` command
    from writing the same day twice.
    """
    try:
        with dataset_lock(MODULE_ID, DATASET_KEY):
            snapshot = get_complete_market_snapshot(business_date)
            try:
                industry_version = get_complete_industry_snapshot_version()
            except CompleteIndustrySnapshotUnavailable as error:
                raise CompleteMarketDataUnavailable(str(error)) from error
            analysis = build_sector_momentum_analysis(snapshot, industry_version)
            write_result = write_sector_momentum_analysis(
                business_date=business_date,
                analysis=analysis,
            )
    except DatasetLocked as error:
        # 锁被占用不是"数据不可用"：调用方据此决定是返回旧数据还是 409。
        raise DatasetBusy(
            f'The sector-momentum ranking for {business_date.isoformat()} is being generated.'
        ) from error
    return SectorMomentumResult.objects.using('sector_momentum').get(pk=write_result.result_id)


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
            f'{result.unmapped_stock_count} 只有效股票未映射到开盘啦板块。'
        )
    if stale:
        warnings.append('公共行情或开盘啦行业映射已更新，正在展示最近可用的分析结果。')
    return tuple(warnings)


READ_PATH = ReadPath(
    module_id=MODULE_ID,
    results=lambda: SectorMomentumResult.objects.using('sector_momentum'),
    generate=_local_generate,
    serialize=_serialize,
    warnings=_warnings,
    latest_public_date=lambda: latest_complete_stock_price_date(),
    industry_version=lambda: get_complete_industry_snapshot_version(),
    industry_unavailable=CompleteIndustrySnapshotUnavailable,
    file_cache=lambda: default_file_cache(),
    no_result_message='No sector-momentum analysis result is available.',
)


def read_sector_momentum(trade_date: date | None = None) -> ReadResult:
    """Read a ranking, generating it locally when the requested day has none.

    Logged for the same reason as the other two modules: a plain page request can
    silently turn into a local computation or a stale fallback, and neither shows
    up in the access log.
    """
    return _read(READ_PATH, trade_date)


def read_dates() -> ReadResult:
    return _read_dates(READ_PATH)
