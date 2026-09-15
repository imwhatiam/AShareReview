"""Cache-first reads and on-demand local generation for hundred-day results.

The cache/fallback sequence itself lives in ``core.services.read_path``; this
module only declares what is genuinely hundred-day's: how to generate a day, how
to serialize it, and what to warn about. ``InsufficientHundredDayHistory`` is
registered as an "unavailable" error so a page request can be answered with a
specific reason instead of a generic failure.

读路径拿到的"结果"是这一天市场宽度里最新的那一点（``trade_date`` 等于业务日期
的那一行）：它就是当日汇总。行业级的新高/新低数量与名单都在这里由个股标志按
``industries`` 分组现算，与写入时逐行业展开的结果一致。
"""

from datetime import date
from decimal import Decimal

from core.services.file_cache import default_file_cache
from core.services.locking import DatasetBusy, DatasetLocked, dataset_lock
from core.services.market_data import (
    CompleteMarketDataUnavailable,
    latest_complete_stock_price_date,
)
from core.services.read_path import ReadPath, ReadResult  # noqa: F401
from core.services.read_path import read as _read
from core.services.read_path import read_dates as _read_dates
from hundred_day.models import (
    HundredDayBreadth,
    HundredDayIndustrySummary,
    HundredDayStockFlag,
)
from hundred_day.services.analysis import (
    InsufficientHundredDayHistory,
    build_hundred_day_analysis,
)
from hundred_day.services.industry_source import (
    CompleteIndustrySnapshotUnavailable,
    require_industry_snapshot,
)
from hundred_day.services.source_data import load_hundred_day_source_data
from hundred_day.services.writer import write_hundred_day_analysis

MODULE_ID = 'hundred_day'
DATASET_KEY = 'hundred_day'

# 趋势点的比值以前是 DecimalField(decimal_places=8)，ORM 读回时会 quantize 到 8 位。
# 现在由除法现算，所以收尾到同样的位数，报文里的数字串与改动前逐字符一致。
# 「当日」那两个比值从来没落过库（一直是现算的），所以它们**不收尾**。
_TREND_RATIO_PLACES = 8


def _local_generate(business_date: date) -> HundredDayBreadth:
    """Generate the hundred-day flags from already-local rows only.

    This path never contacts upstream APIs. It is the heaviest of the three
    on-demand generations because it reads roughly 199 trading days of local
    closes, so the dataset lock keeps a concurrent request or a running
    ``build_hundred_day`` command from doing the same work twice.
    """
    try:
        with dataset_lock(MODULE_ID, DATASET_KEY):
            source = load_hundred_day_source_data(business_date)
            try:
                require_industry_snapshot()
            except CompleteIndustrySnapshotUnavailable as error:
                raise CompleteMarketDataUnavailable(str(error)) from error
            analysis = build_hundred_day_analysis(source)
            write_result = write_hundred_day_analysis(analysis=analysis)
    except DatasetLocked as error:
        # 锁被占用不是"数据不可用"：调用方据此决定是返回旧数据还是 409。
        raise DatasetBusy(
            f'The hundred-day analysis for {business_date.isoformat()} is being generated.'
        ) from error
    # 刚写进去的市场宽度里最新的那一点就是业务日期本身 —— 它就是"当日结果"。
    return (
        HundredDayBreadth.objects.using('hundred_day')
        .filter(business_date=write_result.business_date)
        .order_by('trade_date')
        .last()
    )


def _ratio_text(count: int, total: int, *, places: int | None) -> str | None:
    if not total:
        return None
    value = Decimal(count) / Decimal(total)
    if places is not None:
        value = value.quantize(Decimal(1).scaleb(-places))
    return str(value)


def _flagged_stocks_by_industry(stock_flags) -> dict[str, dict[str, list[dict]]]:
    """Rebuild each industry's new-high / new-low stock lists from the stock flags.

    行业明细名单不再落库，它可以从个股标志按 ``industries`` 分组精确重建。按
    ``stock_code`` 升序遍历，重建出的顺序与原先落库的那份 JSON 一致；一只股票属于
    多个行业时会出现在每个行业的名单里，同样与写入时逐行业展开的结果一致。

    ``change_percent`` / ``turnover`` 直接给 ``Decimal``，由响应编码器转成字符串，
    与旧 JSON 里存字符串的最终报文相同。
    """
    grouped: dict[str, dict[str, list[dict]]] = {}
    for flag in stock_flags:
        detail = {
            'code': flag.stock_code,
            'name': flag.stock_name,
            'change_percent': flag.change_percent,
            'turnover': flag.turnover,
        }
        for industry in flag.industries:
            bucket = grouped.setdefault(industry['code'], {'new_high': [], 'new_low': []})
            if flag.is_new_high:
                bucket['new_high'].append(detail)
            if flag.is_new_low:
                bucket['new_low'].append(detail)
    return grouped


def _serialize(result) -> dict:
    business_date = result.business_date
    stock_flags = list(
        HundredDayStockFlag.objects.using('hundred_day')
        .filter(business_date=business_date)
        .order_by('stock_code')
    )
    flagged_by_industry = _flagged_stocks_by_industry(stock_flags)
    empty_lists = {'new_high': [], 'new_low': []}
    # 这一次发布的全部市场宽度点；最新的那一点（trade_date 最大的）就是当日结果。
    breadth = list(
        HundredDayBreadth.objects.using('hundred_day')
        .filter(business_date=business_date)
        .order_by('trade_date')
    )
    current = max(breadth, key=lambda point: point.trade_date)
    return {
        'trade_date': str(business_date),
        'totals': {
            'valid_stock_count': current.valid_stock_count,
            'new_high_count': current.new_high_count,
            'new_low_count': current.new_low_count,
            'new_high_ratio': _ratio_text(
                current.new_high_count, current.valid_stock_count, places=None
            ),
            'new_low_ratio': _ratio_text(
                current.new_low_count, current.valid_stock_count, places=None
            ),
        },
        'industry_summaries': [
            {
                'industry_code': summary.industry_code,
                'industry_name': summary.industry_name,
                'stock_count': summary.stock_count,
                # 计数与名单来自同一次分组，所以它们永远不会互相矛盾。
                'new_high_count': len(
                    flagged_by_industry.get(summary.industry_code, empty_lists)['new_high']
                ),
                'new_low_count': len(
                    flagged_by_industry.get(summary.industry_code, empty_lists)['new_low']
                ),
                'new_high_stocks': flagged_by_industry.get(
                    summary.industry_code, empty_lists
                )['new_high'],
                'new_low_stocks': flagged_by_industry.get(
                    summary.industry_code, empty_lists
                )['new_low'],
            }
            for summary in HundredDayIndustrySummary.objects.using('hundred_day')
            .filter(business_date=business_date)
            .order_by('industry_code')
        ],
        'stock_flags': [
            {
                'code': flag.stock_code,
                'name': flag.stock_name,
                'industries': flag.industries,
                'is_new_high': flag.is_new_high,
                'is_new_low': flag.is_new_low,
            }
            for flag in stock_flags
        ],
        'trend': [
            {
                'trade_date': str(point.trade_date),
                'valid_stock_count': point.valid_stock_count,
                'new_high_count': point.new_high_count,
                'new_low_count': point.new_low_count,
                'new_high_ratio': _ratio_text(
                    point.new_high_count, point.valid_stock_count, places=_TREND_RATIO_PLACES
                ),
                'new_low_ratio': _ratio_text(
                    point.new_low_count, point.valid_stock_count, places=_TREND_RATIO_PLACES
                ),
            }
            for point in breadth
        ],
    }


def _warnings(_result, stale: bool) -> tuple[str, ...]:
    return (
        ('正在展示最近可用的百日分析结果，当日结果可能尚未生成。',) if stale else ()
    )


READ_PATH = ReadPath(
    module_id=MODULE_ID,
    results=lambda: HundredDayBreadth.objects.using('hundred_day'),
    generate=_local_generate,
    serialize=_serialize,
    warnings=_warnings,
    latest_public_date=lambda: latest_complete_stock_price_date(),
    file_cache=lambda: default_file_cache(),
    unavailable_errors=(InsufficientHundredDayHistory,),
    no_result_message='No hundred-day analysis result is available.',
)


def read_hundred_day(trade_date: date | None = None) -> ReadResult:
    """Read the flags, generating them locally when the requested day has none.

    Logged like the other two modules; ``insufficient_history`` is its own event
    because it means "the local price history is too short", not "the day is
    missing" — an operator fixes those two very differently.
    """
    return _read(READ_PATH, trade_date)


def read_dates() -> ReadResult:
    return _read_dates(READ_PATH)
