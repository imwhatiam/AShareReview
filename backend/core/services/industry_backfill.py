"""Add the industry members the Kaipanla snapshot cannot classify.

Kaipanla's 881 industry lists still carry the pre-2026 Beijing Stock Exchange
codes (43/83/87), while the local stock master only knows the 920xxx re-codes.
Every BSE stock therefore ends up with no industry at all, which is what made
`unmapped_stock_count` jump from 5 to 313 when the project switched to the 881
family.

Hithink publishes the same taxonomy with current codes: the two vendors agree
on 90 industry codes *and* names, and every Hithink industry is a superset of
its Kaipanla counterpart. So this module only ever *adds* members — it never
removes or rewrites a membership Kaipanla produced.
"""

from typing import Any

from backend.env import get_bool_setting
from core.integrations.hithink.client import HithinkClient
from core.logging import ProgressReporter
from core.models import Stock


BACKFILL_ENABLED_SETTING = 'HITHINK_INDUSTRY_BACKFILL_ENABLED'


def _locally_known_stock_codes(candidates: set[str]) -> set[str]:
    """Keep only codes the local stock master knows about.

    A membership for a stock that is not in ``core_stock`` can never match a
    daily price, so it would be dead weight in the snapshot.
    """
    if not candidates:
        return set()
    return set(
        Stock.objects.filter(stock_code__in=candidates).values_list(
            'stock_code', flat=True
        )
    )


def backfill_missing_industry_stocks(records, *, client=None) -> int:
    """Add missing members to industries and return how many were added.

    ``records`` is the mutable record list built by the Kaipanla collector; the
    matching industry records are updated in place. The return value counts
    distinct stock codes that gained a membership.
    """
    if not get_bool_setting(BACKFILL_ENABLED_SETTING, default=True):
        return 0

    industries_by_code: dict[str, dict[str, Any]] = {
        record['industry_code']: record for record in records
    }
    if not industries_by_code:
        return 0

    # 同花顺的 320 个行业里只有与开盘啦同代码的那些能对上，剩下的是更细的 884xxx 细分指数，
    # 它们的并集是 881xxx 的子集，补进去只会制造重叠，所以直接跳过。
    upstream = HithinkClient() if client is None else client
    indices = [
        index
        for index in upstream.list_industry_indices()
        if index.industry_code in industries_by_code
    ]

    # 每个行业一次请求（上游不接受批量），是这条命令里第二段长活儿：和抓取阶段一样，
    # 需要能看出是在走还是卡住。
    progress = ProgressReporter('hithink_industry_backfill', total=len(indices))
    progress.start(action='started', industries=len(indices))

    added_stock_codes: set[str] = set()
    for index in indices:
        record = industries_by_code[index.industry_code]
        known = set(record['stock_codes'])
        constituents = set(upstream.list_industry_constituents(index.thscode))
        missing = _locally_known_stock_codes(constituents - known)
        if missing:
            record['stock_codes'] = sorted(known | missing)
            added_stock_codes.update(missing)
        progress.advance(industry=index.industry_name, added=len(added_stock_codes))

    progress.report(force=True, action='completed', added=len(added_stock_codes))
    return len(added_stock_codes)
