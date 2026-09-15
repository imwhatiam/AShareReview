"""Cache-first reads and on-demand local generation for stock-move results.

The cache/fallback sequence itself lives in ``core.services.read_path``; this
module only declares what is genuinely stock-moves': how to generate a day, how
to serialize it, and what to warn about.

本模块只有一张表，所以没有"结果行"可以返回：读路径拿到的那一天由
:class:`StockMoveDay` 表示，它只带 ``business_date`` 与这一天的发布时间。六组计数、
去重股票数与非致命告警都在 :func:`_serialize` / :func:`_warnings` 里由这一天的行
现算 —— 这些数字是同一批行的函数，单独存一份只会多一处可能不一致的副本。
"""

from dataclasses import dataclass
from datetime import date, datetime

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
from stock_moves.models import StockMoveItem
from stock_moves.services.analysis import build_stock_move_analysis
from stock_moves.services.industry_source import (
    CompleteIndustrySnapshotUnavailable,
    require_industry_snapshot,
)
from stock_moves.services.writer import write_stock_move_analysis

MODULE_ID = 'stock_moves'
DATASET_KEY = 'stock_moves'


@dataclass(frozen=True)
class StockMoveDay:
    """One published business day: the anchor every row of that day shares.

    这一天一行都没有（没有任何股票同时满足成交额与涨跌幅阈值）时，表里就没有
    这一天，读路径也只能用它表示 —— 页面照样渲染一个全空的看板，而不是把这一天
    报成"没有数据"。
    """

    business_date: date
    published_at: datetime


def _rows_for(business_date: date):
    """One day's rows in page order: 上证涨/跌 → 深证涨/跌 → 北交所涨/跌，组内按排名。"""
    return (
        StockMoveItem.objects.using('stock_moves')
        .filter(business_date=business_date)
        .order_by('group', 'rank')
    )


def _local_generate(business_date: date) -> StockMoveDay:
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
                require_industry_snapshot()
            except CompleteIndustrySnapshotUnavailable as error:
                # 没有行业映射就没法写出 industries 字段，宁可"生成不了"也不要
                # 落一份缺字段的结果（读路径会退回旧数据并标 stale）。
                raise CompleteMarketDataUnavailable(str(error)) from error
            analysis = build_stock_move_analysis(snapshot)
            write_result = write_stock_move_analysis(
                business_date=business_date,
                analysis=analysis,
            )
    except DatasetLocked as error:
        # 锁被占用不是"数据不可用"：调用方据此决定是返回旧数据还是 409。
        raise DatasetBusy(
            f'The stock-move analysis for {business_date.isoformat()} is being generated.'
        ) from error
    return StockMoveDay(write_result.business_date, write_result.published_at)


def _serialize(result) -> dict:
    rows = list(_rows_for(result.business_date))
    groups: dict[str, list[dict]] = {choice: [] for choice in StockMoveItem.Group.values}
    for item in rows:
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
            group: len(groups[group]) for group in StockMoveItem.Group.values
        },
        # 「全部复制」直接消费这个数组，所以顺序按页面分组顺序（上证涨/跌 → 深证涨/跌
        # → 北交所涨/跌，组内按排名）返回 —— 用户复制出来的顺序与他看到的看板一致。
        'stock_codes': list(dict.fromkeys(
            item['code']
            for group_key in StockMoveItem.Group.values
            for item in groups[group_key]
        )),
        'distinct_stock_count': len({item.stock_code for item in rows}),
    }


def _warnings(result, stale: bool) -> tuple[str, ...]:
    """Derive the day's non-fatal warnings from its rows.

    按页面顺序（分组 + 组内排名）生成，也就是用户看到的看板顺序。这两条告警从来
    不是独立的字段：写入时那一次同义计算已在 2026-09-15 删除，只留这一处。
    """
    warnings: list[str] = []
    for item in _rows_for(result.business_date):
        if not item.stock_name:
            warnings.append(f'股票 {item.stock_code} 名称缺失。')
        if not item.industries:
            warnings.append(f'股票 {item.stock_code} 未映射到开盘啦板块。')
    warnings = list(dict.fromkeys(warnings))
    if stale:
        warnings.append('正在展示最近可用的分析结果，当日结果可能尚未生成。')
    return tuple(warnings)


READ_PATH = ReadPath(
    module_id=MODULE_ID,
    results=lambda: StockMoveItem.objects.using('stock_moves'),
    generate=_local_generate,
    serialize=_serialize,
    warnings=_warnings,
    latest_public_date=lambda: latest_complete_stock_price_date(),
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
