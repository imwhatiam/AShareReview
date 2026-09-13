"""Cache-first reads and on-demand local generation for hundred-day results.

The cache/version/fallback sequence itself lives in ``core.services.read_path``;
this module only declares what is genuinely hundred-day's: how to generate a
day, how to serialize it, and what to warn about. ``InsufficientHundredDayHistory``
is registered as an "unavailable" error so a page request can be answered with a
specific reason instead of a generic failure.
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

MODULE_ID = 'hundred_day'
DATASET_KEY = 'hundred_day'


def _local_generate(business_date: date) -> HundredDayResult:
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
                industry_version = get_complete_industry_snapshot_version()
            except CompleteIndustrySnapshotUnavailable as error:
                raise CompleteMarketDataUnavailable(str(error)) from error
            analysis = build_hundred_day_analysis(
                source, source_industry_version=industry_version
            )
            write_result = write_hundred_day_analysis(analysis=analysis)
    except DatasetLocked as error:
        # 锁被占用不是"数据不可用"：调用方据此决定是返回旧数据还是 409。
        raise DatasetBusy(
            f'The hundred-day analysis for {business_date.isoformat()} is being generated.'
        ) from error
    return HundredDayResult.objects.using('hundred_day').get(pk=write_result.result_id)


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
                'industries': flag.industries,
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


def _warnings(_result: HundredDayResult, stale: bool) -> tuple[str, ...]:
    return (
        ('公共日行情或行业映射版本已更新，正在展示最近可用的百日分析结果。',)
        if stale else ()
    )


READ_PATH = ReadPath(
    module_id=MODULE_ID,
    results=lambda: HundredDayResult.objects.using('hundred_day'),
    generate=_local_generate,
    serialize=_serialize,
    warnings=_warnings,
    latest_public_date=lambda: latest_complete_stock_price_date(),
    industry_version=lambda: get_complete_industry_snapshot_version(),
    industry_unavailable=CompleteIndustrySnapshotUnavailable,
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
