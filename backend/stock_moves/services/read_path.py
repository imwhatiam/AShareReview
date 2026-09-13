"""Cache-first reads and on-demand local generation for stock-move results.

The cache/version/fallback sequence itself lives in ``core.services.read_path``;
this module only declares what is genuinely stock-moves': how to generate a day,
how to serialize it, and what to warn about.
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
from stock_moves.models import StockMoveItem, StockMoveResult
from stock_moves.services.analysis import build_stock_move_analysis
from stock_moves.services.source_versions import (
    CompleteIndustrySnapshotUnavailable,
    get_complete_industry_snapshot_version,
)
from stock_moves.services.writer import write_stock_move_analysis

MODULE_ID = 'stock_moves'
DATASET_KEY = 'stock_moves'


def _local_generate(business_date: date) -> StockMoveResult:
    """Generate one trading day's analysis from already-local core data only.

    This path never synchronizes upstream data: it is a local computation over a
    single day of prices, so there is no row budget to enforce. A request that
    lands on a day without a stored result generates it instead of showing
    nothing. The dataset lock keeps a concurrent request or a running
    ``build_stock_moves`` command from writing the same day twice.
    """
    try:
        with dataset_lock(MODULE_ID, DATASET_KEY):
            snapshot = get_complete_market_snapshot(business_date)
            try:
                industry_version = get_complete_industry_snapshot_version()
            except CompleteIndustrySnapshotUnavailable as error:
                # 没有行业映射就没法写出 industries 字段，宁可"生成不了"也不要
                # 落一份缺字段的结果（读路径会退回旧数据并标 stale）。
                raise CompleteMarketDataUnavailable(str(error)) from error
            analysis = build_stock_move_analysis(snapshot)
            write_result = write_stock_move_analysis(
                business_date=business_date,
                source_daily_price_version=snapshot.data_version.version,
                source_industry_version=industry_version,
                analysis=analysis,
            )
    except DatasetLocked as error:
        # 锁被占用不是"数据不可用"：调用方据此决定是返回旧数据还是 409。
        raise DatasetBusy(
            f'The stock-move analysis for {business_date.isoformat()} is being generated.'
        ) from error
    return StockMoveResult.objects.using('stock_moves').get(pk=write_result.result_id)


def _serialize(result: StockMoveResult) -> dict:
    groups: dict[str, list[dict]] = {choice: [] for choice in StockMoveItem.Group.values}
    for item in result.items.all().order_by('group', 'rank'):
        groups[item.group].append({
            'rank': item.rank,
            'code': item.stock_code,
            'name': item.stock_name,
            'industries': item.industries,
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
            StockMoveItem.Group.BSE_RISE: result.bse_rise_count,
            StockMoveItem.Group.BSE_FALL: result.bse_fall_count,
        },
        # 「全部复制」直接消费这个数组，所以顺序按页面分组顺序（上证涨/跌 → 深证涨/跌
        # → 北交所涨/跌，组内按排名）返回 —— 用户复制出来的顺序与他看到的看板一致。
        'stock_codes': list(dict.fromkeys(
            item['code']
            for group_key in StockMoveItem.Group.values
            for item in groups[group_key]
        )),
        'distinct_stock_count': result.distinct_stock_count,
    }


def _warnings(result: StockMoveResult, stale: bool) -> tuple[str, ...]:
    warnings = list(result.warnings)
    if stale:
        warnings.append('公共行情或开盘啦行业映射已更新，正在展示最近可用的分析结果。')
    return tuple(dict.fromkeys(warnings))


READ_PATH = ReadPath(
    module_id=MODULE_ID,
    results=lambda: StockMoveResult.objects.using('stock_moves'),
    generate=_local_generate,
    serialize=_serialize,
    warnings=_warnings,
    latest_public_date=lambda: latest_complete_stock_price_date(),
    industry_version=lambda: get_complete_industry_snapshot_version(),
    industry_unavailable=CompleteIndustrySnapshotUnavailable,
    file_cache=lambda: default_file_cache(),
    no_result_message='No stock-move analysis result is available.',
)


def read_stock_moves(trade_date: date | None = None) -> ReadResult:
    """Read a derived result from cache or SQLite, generating it locally when absent.

    Wrapped in logging because this is the one path where a plain page request can
    silently become slow (local generation) or silently serve yesterday's data
    (stale fallback); the access log alone cannot tell those apart.
    """
    return _read(READ_PATH, trade_date)


def read_dates() -> ReadResult:
    return _read_dates(READ_PATH)
