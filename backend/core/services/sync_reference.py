"""Synchronization for public stock master data.

Trading days are deliberately absent here: they are not upstream data, and are
derived locally from ``chinese-calendar`` by ``core.services.calendar``.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ImproperlyConfigured
from django.db import transaction

from backend.env import get_setting
from core.integrations.hithink.client import HithinkClient
from core.integrations.hithink.contracts import HithinkTicker
from core.logging import ProgressReporter
from core.models import Stock

# 股票主数据同步的最后一步是"把本次没出现的股票置为 inactive"。上游某次少返回
# 若干页却不报错时，这一步会把大批股票静默停用，之后不再为它们采集行情。所以先用
# 这个比例做下界校验：本次结果低于「现有活跃股票数 × 比例」就整体失败，绝不写入。
_STOCK_MASTER_MIN_COVERAGE_DEFAULT = '0.9'


@dataclass(frozen=True)
class ReferenceSyncResult:
    dataset_key: str
    record_count: int
    dry_run: bool


def _collect_tickers(client: HithinkClient, page_size: int) -> tuple[HithinkTicker, ...]:
    tickers = []
    offset = 0
    # 总数事先未知，所以只报"已取多少 / 当前偏移"，足以区分在走和卡住。
    progress = ProgressReporter('stock_master', page_size=page_size)
    progress.start(action='fetching_tickers')
    while True:
        page = client.list_a_share_tickers(limit=page_size, offset=offset)
        tickers.extend(page)
        progress.advance(page_size=len(page), offset=offset, tickers=len(tickers))
        if len(page) < page_size:
            break
        offset += page_size

    progress.report(force=True, action='fetched_tickers', tickers=len(tickers))

    if not tickers:
        raise ValueError('Hithink returned an empty A-share ticker list.')
    thscodes = [ticker.thscode for ticker in tickers]
    stock_codes = [ticker.stock_code for ticker in tickers]
    if len(thscodes) != len(set(thscodes)) or len(stock_codes) != len(set(stock_codes)):
        raise ValueError('Hithink returned duplicate A-share ticker identifiers.')
    return tuple(tickers)


def _stock_master_min_coverage_ratio() -> Decimal:
    raw = get_setting(
        'STOCK_MASTER_MIN_COVERAGE_RATIO', _STOCK_MASTER_MIN_COVERAGE_DEFAULT
    )
    try:
        ratio = Decimal(str(raw).strip())
    except (TypeError, InvalidOperation) as error:
        raise ImproperlyConfigured(
            'STOCK_MASTER_MIN_COVERAGE_RATIO must be numeric.'
        ) from error
    if not Decimal('0') < ratio <= Decimal('1'):
        raise ImproperlyConfigured(
            'STOCK_MASTER_MIN_COVERAGE_RATIO must be within (0, 1].'
        )
    return ratio


def _validate_stock_master_coverage(tickers: tuple[HithinkTicker, ...]) -> None:
    """Refuse to deactivate the market just because upstream returned fewer rows.

    只有已经同步过一次（库里有活跃股票）时才校验；首次同步没有可比基线。
    """
    active_count = Stock.objects.filter(is_active=True).count()
    if active_count == 0:
        return
    ratio = _stock_master_min_coverage_ratio()
    minimum = int(Decimal(active_count) * ratio)
    if len(tickers) >= minimum:
        return
    raise ValueError(
        f'Hithink returned {len(tickers)} A-share tickers, below the {minimum} '
        f'required to keep {ratio:.0%} of the {active_count} active stocks; '
        'refusing to deactivate the missing ones.'
    )


def sync_stock_master(*, page_size: int = 1000, dry_run: bool = False):
    """Replace the stock master in one transaction.

    Nothing is written until the whole list has been fetched and its coverage
    checked, so a bad upstream page can never leave the market half-deactivated.
    """
    if not 1 <= page_size <= 10000:
        raise ValueError('page_size must be between 1 and 10000.')
    tickers = _collect_tickers(HithinkClient(), page_size)
    _validate_stock_master_coverage(tickers)
    if dry_run:
        return ReferenceSyncResult('stock_master', len(tickers), True)

    with transaction.atomic():
        Stock.objects.exclude(thscode__in=[ticker.thscode for ticker in tickers]).update(
            is_active=False
        )
        for ticker in tickers:
            Stock.objects.update_or_create(
                thscode=ticker.thscode,
                defaults={
                    'stock_code': ticker.stock_code,
                    'stock_name': ticker.stock_name,
                    'exchange': ticker.exchange,
                    'is_active': True,
                },
            )
    return ReferenceSyncResult('stock_master', len(tickers), False)
