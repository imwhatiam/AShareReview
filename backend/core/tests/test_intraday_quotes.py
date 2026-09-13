"""Intraday whole-market snapshot refresh: paging, conventions, publication."""

import os
from datetime import date
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from core.integrations.hithink.contracts import (
    HithinkQuoteSnapshot,
    HithinkUnavailableError,
)
from core.models import DailyPrice, DataVersion, Stock, TradingDay
from core.services.sync_daily_prices import refresh_intraday_daily_prices


class FakeSnapshotClient:
    """Serve a flat quote list through ``limit`` / ``offset`` pages."""

    def __init__(self, quotes=(), *, error=None):
        self.quotes = tuple(quotes)
        self.error = error
        self.calls = []

    def list_market_quotes(self, *, limit, offset):
        self.calls.append((limit, offset))
        if self.error is not None:
            raise self.error
        return self.quotes[offset:offset + limit], len(self.quotes)


def _quote(thscode, ticker, price, *, volume=1000):
    """Build a quote whose OHLC are all ``price``, so tests vary one number."""
    last = Decimal(price)
    return HithinkQuoteSnapshot(
        thscode=thscode,
        stock_code=ticker,
        last_price=last,
        open_price=last,
        high_price=last,
        low_price=last,
        volume=volume,
        turnover=last * volume,
    )


def _halted_quote(thscode, ticker):
    """A suspended stock: still listed, but with no price and no volume."""
    return HithinkQuoteSnapshot(
        thscode=thscode,
        stock_code=ticker,
        last_price=None,
        open_price=None,
        high_price=None,
        low_price=None,
        volume=None,
        turnover=None,
    )


class IntradayQuoteRefreshTests(TestCase):
    def setUp(self):
        self.previous_day = date(2026, 9, 10)
        self.day = date(2026, 9, 11)
        TradingDay.objects.create(trade_date=self.previous_day)
        TradingDay.objects.create(trade_date=self.day)
        self.stock = Stock.objects.create(
            thscode='000001.SZ',
            stock_code='000001',
            stock_name='平安银行',
            exchange=Stock.Exchange.SZSE,
        )
        self.other = Stock.objects.create(
            thscode='600000.SH',
            stock_code='600000',
            stock_name='浦发银行',
            exchange=Stock.Exchange.SSE,
        )

    def _store_previous_close(self, stock, close):
        return DailyPrice.objects.create(
            stock=stock,
            trade_date=self.previous_day,
            pre_close=Decimal(close),
            close_price=Decimal(close),
            has_valid_trade=True,
            source_batch_id='previous-batch',
            source_data_version='previous-version',
        )

    def _both_quotes(self, *, first='11.0', second='22.0'):
        return (
            _quote(self.stock.thscode, self.stock.stock_code, first),
            _quote(self.other.thscode, self.other.stock_code, second),
        )

    def _refresh(self, client, **kwargs):
        with patch(
            'core.services.sync_daily_prices._intraday_quote_page_size',
            return_value=2,
        ):
            return refresh_intraday_daily_prices(
                trade_date=self.day, client=client, **kwargs
            )

    def test_refresh_publishes_one_complete_version_covering_the_whole_market(self):
        self._store_previous_close(self.stock, '10.0')
        self._store_previous_close(self.other, '20.0')

        result = self._refresh(FakeSnapshotClient(self._both_quotes()))

        self.assertTrue(result.published)
        self.assertEqual(result.matched_stock_count, 2)
        self.assertEqual(result.coverage_ratio, Decimal('1'))
        row = DailyPrice.objects.get(stock=self.stock, trade_date=self.day)
        self.assertEqual(row.close_price, Decimal('11.0000'))
        self.assertEqual(row.pre_close, Decimal('10.0000'))
        self.assertEqual(row.change_percent, Decimal('10.000000'))
        self.assertTrue(row.has_valid_trade)
        version = DataVersion.objects.get(
            dataset_key='stock_daily_prices',
            business_date=self.day,
            status=DataVersion.Status.COMPLETE,
        )
        self.assertEqual(version.expected_record_count, 2)
        self.assertEqual(version.actual_record_count, 2)
        self.assertEqual(
            set(
                DailyPrice.objects.filter(trade_date=self.day).values_list(
                    'source_data_version', flat=True
                )
            ),
            {version.version},
        )

    def test_refresh_walks_every_snapshot_page(self):
        self._store_previous_close(self.stock, '10.0')
        self._store_previous_close(self.other, '20.0')

        client = FakeSnapshotClient(self._both_quotes())
        self._refresh(client)

        # page size 2 over 2 quotes: one full page, then a short/empty page.
        self.assertEqual(client.calls, [(2, 0), (2, 2)])

    def test_refresh_updates_existing_rows_instead_of_duplicating_them(self):
        self._store_previous_close(self.stock, '10.0')
        self._store_previous_close(self.other, '20.0')
        DailyPrice.objects.create(
            stock=self.stock,
            trade_date=self.day,
            close_price=Decimal('10.5'),
            has_valid_trade=True,
            source_batch_id='intraday-batch',
            source_data_version='intraday-version',
        )

        self._refresh(FakeSnapshotClient(self._both_quotes()))

        self.assertEqual(DailyPrice.objects.filter(trade_date=self.day).count(), 2)
        row = DailyPrice.objects.get(stock=self.stock, trade_date=self.day)
        self.assertEqual(row.close_price, Decimal('11.0000'))
        self.assertNotEqual(row.source_data_version, 'intraday-version')

    def test_refresh_records_a_suspended_stock_as_a_non_trading_record(self):
        self._store_previous_close(self.stock, '10.0')
        self._store_previous_close(self.other, '20.0')

        self._refresh(FakeSnapshotClient((
            _halted_quote(self.stock.thscode, self.stock.stock_code),
            _quote(self.other.thscode, self.other.stock_code, '22.0'),
        )))

        row = DailyPrice.objects.get(stock=self.stock, trade_date=self.day)
        self.assertFalse(row.has_valid_trade)
        self.assertIsNone(row.close_price)
        self.assertIsNone(row.open_price)
        self.assertIsNone(row.pre_close)
        self.assertIsNone(row.change_percent)
        # 停牌不能把上游的 0 写进成交量：那会让这行看起来“成交过”。
        self.assertIsNone(row.volume)
        self.assertIsNone(row.turnover)

    def test_refresh_computes_the_change_from_the_stored_previous_close(self):
        """除权除息日上游涨跌幅用的是未复权前收，与本序列口径不同。"""
        self._store_previous_close(self.stock, '10.0')
        self._store_previous_close(self.other, '20.0')

        self._refresh(FakeSnapshotClient((
            _quote(self.stock.thscode, self.stock.stock_code, '11.0'),
            _quote(self.other.thscode, self.other.stock_code, '22.0'),
        )))

        row = DailyPrice.objects.get(stock=self.stock, trade_date=self.day)
        self.assertEqual(row.pre_close, Decimal('10.0000'))
        self.assertEqual(row.change_percent, Decimal('10.000000'))

    def test_refresh_leaves_the_change_empty_without_a_stored_previous_close(self):
        """新股/复牌当日本地没有前收，涨跌幅必须留空而不是编一个出来。"""
        result = self._refresh(FakeSnapshotClient(self._both_quotes()))

        self.assertTrue(result.published)
        row = DailyPrice.objects.get(stock=self.stock, trade_date=self.day)
        self.assertIsNone(row.pre_close)
        self.assertIsNone(row.change_percent)
        self.assertTrue(row.has_valid_trade)
        self.assertEqual(row.close_price, Decimal('11.0000'))

    def test_refresh_publishes_nothing_when_the_snapshot_has_not_moved(self):
        self._store_previous_close(self.stock, '10.0')
        self._store_previous_close(self.other, '20.0')
        quotes = self._both_quotes()
        self._refresh(FakeSnapshotClient(quotes))
        versions_before = DataVersion.objects.count()
        staging_before = set(DailyPrice.objects.values_list('source_batch_id', flat=True))

        result = self._refresh(FakeSnapshotClient(quotes))

        self.assertFalse(result.published)
        self.assertTrue(result.is_up_to_date)
        self.assertEqual(DataVersion.objects.count(), versions_before)
        self.assertEqual(
            set(DailyPrice.objects.values_list('source_batch_id', flat=True)),
            staging_before,
        )

    def test_refresh_rejects_a_truncated_snapshot_without_writing_anything(self):
        self._store_previous_close(self.stock, '10.0')
        self._store_previous_close(self.other, '20.0')

        client = FakeSnapshotClient((_quote(self.stock.thscode, '000001', '11.0'),))
        # 阈值来自 .env；本用例断言的是"覆盖率不足必须整次拒绝"这条行为，
        # 所以把阈值固定在用例里，避免本机配置不同就让结果变色。
        with patch.dict(os.environ, {'INTRADAY_QUOTE_MIN_COVERAGE_RATIO': '0.9'}):
            with self.assertRaises(ValueError):
                self._refresh(client)

        self.assertFalse(DailyPrice.objects.filter(trade_date=self.day).exists())
        self.assertFalse(
            DataVersion.objects.filter(business_date=self.day).exists()
        )

    def test_refresh_skips_quotes_that_are_not_in_the_stock_master(self):
        """快照里有、本地股票表里没有的代码不能凭空建行。"""
        self._store_previous_close(self.stock, '10.0')
        self._store_previous_close(self.other, '20.0')

        quotes = self._both_quotes() + (
            _quote('900001.SH', '900001', '1.0'),
        )
        self._refresh(FakeSnapshotClient(quotes))

        self.assertEqual(DailyPrice.objects.filter(trade_date=self.day).count(), 2)

    def test_refresh_dry_run_reports_the_diff_without_writing(self):
        self._store_previous_close(self.stock, '10.0')
        self._store_previous_close(self.other, '20.0')

        result = self._refresh(FakeSnapshotClient(self._both_quotes()), dry_run=True)

        self.assertTrue(result.dry_run)
        self.assertFalse(result.published)
        self.assertEqual(result.changed_record_count, 2)
        self.assertFalse(DailyPrice.objects.filter(trade_date=self.day).exists())
        self.assertFalse(
            DataVersion.objects.filter(business_date=self.day).exists()
        )

    def test_refresh_rejects_a_date_outside_the_trading_calendar(self):
        client = FakeSnapshotClient(self._both_quotes())

        with self.assertRaises(ValueError):
            refresh_intraday_daily_prices(
                trade_date=date(2026, 9, 12), client=client
            )

        self.assertEqual(client.calls, [])

    def test_refresh_command_reports_the_refreshed_record_count(self):
        self._store_previous_close(self.stock, '10.0')
        self._store_previous_close(self.other, '20.0')
        client = FakeSnapshotClient(self._both_quotes())

        with (
            patch('core.services.sync_daily_prices.HithinkClient', return_value=client),
            patch(
                'core.services.sync_daily_prices._intraday_quote_page_size',
                return_value=2,
            ),
        ):
            output = StringIO()
            call_command(
                'refresh_intraday_quotes',
                '--date',
                self.day.isoformat(),
                stdout=output,
            )

        self.assertIn(
            f'refreshed 2 intraday records (0 unchanged) for {self.day.isoformat()}',
            output.getvalue(),
        )

    def test_refresh_command_falls_back_to_today_and_rejects_it_when_closed(self):
        """默认日期是今天的上海日期；非交易日必须失败而不是写别的日期。"""
        with patch(
            'core.management.commands.refresh_intraday_quotes._today',
            return_value=date(2026, 9, 12),
        ):
            with self.assertRaises(CommandError):
                call_command('refresh_intraday_quotes')

        self.assertFalse(
            DataVersion.objects.filter(business_date=date(2026, 9, 12)).exists()
        )

    def test_refresh_reports_upstream_failure_as_a_command_error(self):
        self._store_previous_close(self.stock, '10.0')
        self._store_previous_close(self.other, '20.0')
        client = FakeSnapshotClient(error=HithinkUnavailableError('down'))

        with patch('core.services.sync_daily_prices.HithinkClient', return_value=client):
            with self.assertRaises(CommandError):
                call_command(
                    'refresh_intraday_quotes', '--date', self.day.isoformat()
                )

        self.assertFalse(DailyPrice.objects.filter(trade_date=self.day).exists())
