"""Synchronize the public Kaipanla industry-to-stock snapshot."""

from dataclasses import dataclass
from datetime import date
from typing import Any

from core.integrations.kaipanla.client import KaipanlaIndustryClient
from core.logging import ProgressReporter, log_command_progress
from core.models import IndustrySnapshot
from core.services.industry_backfill import backfill_missing_industry_stocks
from core.services.publication import (
    begin_publication,
    fail_publication,
    publish_with_writer,
    set_publication_details,
)

_DATASET_KEY = 'industry_snapshot'


@dataclass(frozen=True)
class IndustrySnapshotSyncResult:
    dataset_key: str
    record_count: int
    dry_run: bool
    business_date: date
    backfilled_stock_count: int = 0


def _normalize_industry(record: Any, label: str) -> tuple[str, str]:
    if not isinstance(record, dict):
        raise ValueError(f'Kaipanla {label} industry record must be an object.')
    code = str(record.get('industry_code', '')).strip()
    name = str(record.get('industry_name', '')).strip()
    if not code or not name:
        raise ValueError(f'Kaipanla {label} industry record is missing a code or name.')
    return code, name


def _normalize_stock_codes(stock_codes: Any, industry_code: str) -> list[str]:
    if not isinstance(stock_codes, (tuple, list)):
        raise ValueError(f'Kaipanla stock list for {industry_code} is invalid.')
    normalized = sorted({str(stock_code).strip() for stock_code in stock_codes if str(stock_code).strip()})
    return normalized


def _collect_industry_snapshot(client: KaipanlaIndustryClient) -> tuple[dict[str, Any], ...]:
    # 行业列表要按页拉（每页一次请求），先声明阶段，避免这段没有输出。
    log_command_progress('kaipanla_industry_snapshot', action='listing_industries')
    industries = tuple(client.list_industries())
    if not industries:
        raise ValueError('Kaipanla returned an empty industry list.')

    # 取成分股是这条命令里唯一的重活儿（每个行业至少一次请求、单次全量要几千次），
    # 也是它过去会安静几十分钟的地方：每个行业取完就推进一步，让操作者能看出是在走还是卡住。
    progress = ProgressReporter('kaipanla_industry_snapshot', industries_total=len(industries))
    progress.start(action='started')

    records: list[dict[str, Any]] = []
    seen_industry_codes: set[str] = set()
    for industry_index, industry in enumerate(industries, start=1):
        industry_code, industry_name = _normalize_industry(industry, 'industry')
        if industry_code in seen_industry_codes:
            raise ValueError(f'Kaipanla returned duplicate industry {industry_code}.')
        seen_industry_codes.add(industry_code)
        stock_codes = _normalize_stock_codes(
            client.list_stock_codes(industry_code), industry_code
        )
        records.append({
            'industry_code': industry_code,
            'industry_name': industry_name,
            'stock_codes': stock_codes,
        })
        progress.advance(
            industry_index=industry_index,
            industry=industry_name,
            stocks=len(stock_codes),
            industries=len(records),
        )

    progress.report(force=True, action='collected', industries=len(records))
    return tuple(records)


def sync_kaipanla_industry_snapshot(*, dry_run: bool = False) -> IndustrySnapshotSyncResult:
    client = KaipanlaIndustryClient()
    # 上游历史接口只服务交易日，所以数据集归属该交易日，而不是本地日期：
    # 周末或节假日运行时两者不同，用本地日期会让版本看起来很新、实际不是。
    business_date = date.fromisoformat(client.request_date)
    if dry_run:
        records = _collect_industry_snapshot(client)
        backfilled_stock_count = backfill_missing_industry_stocks(records)
        return IndustrySnapshotSyncResult(
            _DATASET_KEY, len(records), True, business_date, backfilled_stock_count
        )

    run = begin_publication('core', _DATASET_KEY, None, 0)
    try:
        records = _collect_industry_snapshot(client)
        # 上游历史接口给不出北交所成分股，这里用同花顺补齐；补全失败要整体失败，
        # 否则会安静地退回"313 只有效股票未映射"那个状态。
        backfilled_stock_count = backfill_missing_industry_stocks(records)
        run = set_publication_details(run, len(records), business_date)
    except Exception as error:
        fail_publication(run, error)
        raise

    def write_records():
        IndustrySnapshot.objects.all().delete()
        IndustrySnapshot.objects.bulk_create(
            [IndustrySnapshot(**record) for record in records]
        )

    publish_with_writer(
        run,
        write_records,
        actual_record_count=len(records),
        missing_record_count=0,
    )
    return IndustrySnapshotSyncResult(
        _DATASET_KEY, len(records), False, business_date, backfilled_stock_count
    )
