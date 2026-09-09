"""Synchronization for public stock master data and trading calendar data."""

from dataclasses import dataclass, replace
from typing import Callable

from django.db import transaction

from core.integrations.hithink.client import HithinkClient
from core.integrations.hithink.contracts import HithinkTicker
from core.models import DataVersion, Stock, TradingDay
from core.services.publication import (
    PublicationRun,
    begin_publication,
    fail_publication,
    publish_with_writer,
)


@dataclass(frozen=True)
class ReferenceSyncResult:
    dataset_key: str
    record_count: int
    dry_run: bool


def _set_publication_details(
    run: PublicationRun, record_count: int, business_date
) -> PublicationRun:
    DataVersion.objects.filter(version=run.version).update(
        expected_record_count=record_count,
        business_date=business_date,
    )
    return replace(
        run,
        expected_record_count=record_count,
        business_date=business_date,
    )


def _collect_tickers(client: HithinkClient, page_size: int) -> tuple[HithinkTicker, ...]:
    tickers = []
    offset = 0
    while True:
        page = client.list_a_share_tickers(limit=page_size, offset=offset)
        tickers.extend(page)
        if len(page) < page_size:
            break
        offset += page_size

    if not tickers:
        raise ValueError('Hithink returned an empty A-share ticker list.')
    thscodes = [ticker.thscode for ticker in tickers]
    stock_codes = [ticker.stock_code for ticker in tickers]
    if len(thscodes) != len(set(thscodes)) or len(stock_codes) != len(set(stock_codes)):
        raise ValueError('Hithink returned duplicate A-share ticker identifiers.')
    return tuple(tickers)


def _validate_trading_days(trading_days):
    if not trading_days:
        raise ValueError('Hithink returned an empty trading calendar.')
    if tuple(sorted(trading_days)) != tuple(trading_days):
        raise ValueError('Hithink returned trading days out of ascending order.')
    if len(set(trading_days)) != len(trading_days):
        raise ValueError('Hithink returned duplicate trading days.')
    return tuple(trading_days)


def _publish(
    *,
    dataset_key: str,
    business_date,
    fetch_records: Callable[[], tuple],
    write_records: Callable[[tuple], None],
    dry_run: bool,
) -> ReferenceSyncResult:
    if dry_run:
        records = fetch_records()
        return ReferenceSyncResult(dataset_key, len(records), True)

    run = begin_publication('core', dataset_key, None, 0)
    try:
        records = fetch_records()
        actual_business_date = business_date(records) if callable(business_date) else business_date
        run = _set_publication_details(
            run,
            len(records),
            actual_business_date,
        )
    except Exception as error:
        fail_publication(run, error)
        raise

    publish_with_writer(
        run,
        lambda: write_records(records),
        actual_record_count=len(records),
        missing_record_count=0,
    )
    return ReferenceSyncResult(dataset_key, len(records), False)


def sync_stock_master(*, page_size: int = 1000, dry_run: bool = False):
    if not 1 <= page_size <= 10000:
        raise ValueError('page_size must be between 1 and 10000.')
    client = HithinkClient()

    def fetch_records():
        return _collect_tickers(client, page_size)

    def write_records(tickers):
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

    return _publish(
        dataset_key='stock_master',
        business_date=None,
        fetch_records=fetch_records,
        write_records=write_records,
        dry_run=dry_run,
    )


def sync_trading_calendar(*, dry_run: bool = False):
    client = HithinkClient()

    def fetch_records():
        return _validate_trading_days(client.list_trading_days())

    def write_records(trading_days):
        with transaction.atomic():
            TradingDay.objects.all().delete()
            TradingDay.objects.bulk_create(
                [TradingDay(trade_date=trading_day) for trading_day in trading_days]
            )

    return _publish(
        dataset_key='trading_calendar',
        business_date=lambda trading_days: trading_days[-1],
        fetch_records=fetch_records,
        write_records=write_records,
        dry_run=dry_run,
    )
