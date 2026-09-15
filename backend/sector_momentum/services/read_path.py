"""Cache-first reads and on-demand local generation for sector-momentum results.

The cache/fallback sequence itself lives in ``core.services.read_path``; this
module only declares what is genuinely sector-momentum's: how to generate a
day, how to serialize it, and what to warn about.

本模块只有一张表，所以没有"结果行"可以返回：读路径拿到的那一天由
:class:`SectorMomentumDay` 表示，它带 ``business_date``、发布时间，以及两件日级
事实（全市场成交额、未映射股票数）。名次、股票数、平均涨跌幅、行业成交额、成交额
占比、综合评分都在 :func:`_serialize` 里由 ``stocks`` 现算。
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

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
from sector_momentum.models import SectorMomentumRanking
from sector_momentum.services.analysis import build_sector_momentum_analysis
from sector_momentum.services.industry_source import (
    CompleteIndustrySnapshotUnavailable,
    require_industry_snapshot,
)
from sector_momentum.services.writer import write_sector_momentum_analysis

MODULE_ID = 'sector_momentum'
DATASET_KEY = 'sector_momentum'

# 这几个数值以前是模型字段，字段的 ``decimal_places`` 决定了报文里数字的位数
# （SQLite 存的是 float64，ORM 读回时会 quantize 到 decimal_places）。字段删掉之后
# 位数改在这里声明：读时算出来的值按同样的位数收尾，报文里的数字串与改动前逐字符一致。
_AVERAGE_CHANGE_PERCENT_PLACES = 6
_INDUSTRY_TURNOVER_PLACES = 4
_MARKET_TURNOVER_RATIO_PLACES = 8
_SCORE_PLACES = 12


@dataclass(frozen=True)
class SectorMomentumDay:
    """One published business day: the anchor every row of that day shares.

    排行一行都没有（当日没有任何行业入选）时表里就没有这一天，读路径也只能用它
    表示 —— 页面照样显示全市场成交额与空排行，而不是把这一天报成"没有数据"。
    """

    business_date: date
    published_at: datetime
    total_market_turnover: Decimal
    unmapped_stock_count: int


@dataclass(frozen=True)
class _DerivedRanking:
    """One stored row plus the numbers recomputed from its own stock detail."""

    source: SectorMomentumRanking
    stock_count: int
    average_change_percent: Decimal
    industry_turnover: Decimal
    market_turnover_ratio: Decimal
    score: Decimal


def _quantize(value: Decimal, places: int) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-places))


def _derive(source: SectorMomentumRanking) -> _DerivedRanking:
    """Recompute one ranking's five numbers from its own stock detail.

    Same arithmetic as ``analysis._build_rankings``: ``score`` multiplies the
    **unrounded** average and ratio, and only the serialized numbers are rounded.
    Rounding the intermediates first would change the last digits of ``score``.
    """
    stocks = source.stocks
    stock_count = len(stocks)
    industry_turnover = sum(
        (Decimal(stock['turnover']) for stock in stocks), Decimal('0')
    )
    average_change_percent = (
        sum((Decimal(stock['change_percent']) for stock in stocks), Decimal('0')) / stock_count
        if stock_count
        else Decimal('0')
    )
    total = source.total_market_turnover
    market_turnover_ratio = industry_turnover / total if total else Decimal('0')
    return _DerivedRanking(
        source=source,
        stock_count=stock_count,
        average_change_percent=average_change_percent,
        industry_turnover=industry_turnover,
        market_turnover_ratio=market_turnover_ratio,
        score=stock_count * average_change_percent * market_turnover_ratio,
    )


def _local_generate(business_date: date) -> SectorMomentumDay:
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
                require_industry_snapshot()
            except CompleteIndustrySnapshotUnavailable as error:
                raise CompleteMarketDataUnavailable(str(error)) from error
            analysis = build_sector_momentum_analysis(snapshot)
            write_result = write_sector_momentum_analysis(
                business_date=business_date,
                analysis=analysis,
            )
    except DatasetLocked as error:
        # 锁被占用不是"数据不可用"：调用方据此决定是返回旧数据还是 409。
        raise DatasetBusy(
            f'The sector-momentum ranking for {business_date.isoformat()} is being generated.'
        ) from error
    return SectorMomentumDay(
        business_date=write_result.business_date,
        published_at=write_result.published_at,
        total_market_turnover=analysis.total_market_turnover,
        unmapped_stock_count=analysis.unmapped_stock_count,
    )


def _serialize(result) -> dict:
    derived = [
        _derive(row)
        for row in SectorMomentumRanking.objects.using('sector_momentum')
        .filter(business_date=result.business_date)
        .order_by('metric', 'industry_code')
    ]
    rankings: dict[str, list[dict]] = {
        value: [] for value in SectorMomentumRanking.Metric.values
    }
    for metric in SectorMomentumRanking.Metric.values:
        # 名次不落库：按综合评分降序、同分按行业代码升序，与写入时的排序规则一致。
        ordered = sorted(
            (entry for entry in derived if entry.source.metric == metric),
            key=lambda entry: (-entry.score, entry.source.industry_code),
        )
        for rank, entry in enumerate(ordered, start=1):
            rankings[metric].append({
                'rank': rank,
                'industry_code': entry.source.industry_code,
                'industry_name': entry.source.industry_name,
                'stock_count': entry.stock_count,
                'average_change_percent': _quantize(
                    entry.average_change_percent, _AVERAGE_CHANGE_PERCENT_PLACES
                ),
                'industry_turnover': _quantize(
                    entry.industry_turnover, _INDUSTRY_TURNOVER_PLACES
                ),
                'market_turnover_ratio': _quantize(
                    entry.market_turnover_ratio, _MARKET_TURNOVER_RATIO_PLACES
                ),
                'score': _quantize(entry.score, _SCORE_PLACES),
                'stocks': entry.source.stocks,
            })
    return {
        'trade_date': str(result.business_date),
        'total_market_turnover': result.total_market_turnover,
        'unmapped_stock_count': result.unmapped_stock_count,
        'rankings': rankings,
    }


def _warnings(result, stale: bool) -> tuple[str, ...]:
    warnings: list[str] = []
    if result.unmapped_stock_count:
        warnings.append(
            f'{result.unmapped_stock_count} 只有效股票未映射到开盘啦板块。'
        )
    if stale:
        warnings.append('正在展示最近可用的分析结果，当日结果可能尚未生成。')
    return tuple(warnings)


READ_PATH = ReadPath(
    module_id=MODULE_ID,
    results=lambda: SectorMomentumRanking.objects.using('sector_momentum'),
    generate=_local_generate,
    serialize=_serialize,
    warnings=_warnings,
    latest_public_date=lambda: latest_complete_stock_price_date(),
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
