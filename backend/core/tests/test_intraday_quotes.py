"""Intraday whole-market snapshot refresh: paging, conventions, gating, writing."""

import os
from datetime import date, datetime
from decimal import Decimal
from io import StringIO
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from core.integrations.hithink.contracts import (
    HithinkQuoteSnapshot,
    HithinkUnavailableError,
)
from core.management.commands.refresh_intraday_quotes import Command
from core.models import DailyPrice, Stock
from core.services.sync_daily_prices import refresh_intraday_daily_prices


_SHANGHAI = ZoneInfo('Asia/Shanghai')
# 闸门用例里的"非交易日"：2026-09-12 是周六。
_NON_TRADING_DAY = date(2026, 9, 12)


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
        )

    def _day_rows(self) -> dict[str, tuple]:
        """Snapshot the refreshed day keyed by stock code, batch identity included."""
        return {
            row.stock.stock_code: (
                row.pre_close,
                row.close_price,
                row.change_percent,
                row.has_valid_trade,
                row.source_batch_id,
            )
            for row in DailyPrice.objects.filter(trade_date=self.day).select_related('stock')
        }

    def _both_quotes(self, *, first='11.0', second='22.0'):
        return (
            _quote(self.stock.thscode, self.stock.stock_code, first),
            _quote(self.other.thscode, self.other.stock_code, second),
        )

    def _at(self, day, hour, minute=0):
        """A Shanghai wall clock, used to pin the command's gate and business date."""
        return datetime(day.year, day.month, day.day, hour, minute, tzinfo=_SHANGHAI)

    def _refresh(self, client, **kwargs):
        with patch(
            'core.services.sync_daily_prices._intraday_quote_page_size',
            return_value=2,
        ):
            return refresh_intraday_daily_prices(
                trade_date=self.day, client=client, **kwargs
            )

    def test_refresh_writes_one_batch_covering_the_whole_market(self):
        self._store_previous_close(self.stock, '10.0')
        self._store_previous_close(self.other, '20.0')

        result = self._refresh(FakeSnapshotClient(self._both_quotes()))

        self.assertTrue(result.published)
        self.assertEqual(result.matched_stock_count, 2)
        self.assertEqual(result.coverage_ratio, Decimal('1'))
        self.assertEqual(result.changed_record_count, 2)
        self.assertEqual(result.unchanged_record_count, 0)
        row = DailyPrice.objects.get(stock=self.stock, trade_date=self.day)
        self.assertEqual(row.close_price, Decimal('11.0000'))
        self.assertEqual(row.pre_close, Decimal('10.0000'))
        self.assertEqual(row.change_percent, Decimal('10.000000'))
        self.assertTrue(row.has_valid_trade)
        # 一次刷新就是一个批次：当天两行由同一批次写下 —— 版本表删掉之后，
        # source_batch_id 是"这批数据一起写进来的"唯一凭证。
        batches = {values[4] for values in self._day_rows().values()}
        self.assertEqual(len(batches), 1)
        self.assertNotIn('previous-batch', batches)

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
        )

        self._refresh(FakeSnapshotClient(self._both_quotes()))

        self.assertEqual(DailyPrice.objects.filter(trade_date=self.day).count(), 2)
        row = DailyPrice.objects.get(stock=self.stock, trade_date=self.day)
        self.assertEqual(row.close_price, Decimal('11.0000'))
        # 行被改写，但批次身份不重盖：它回答"这行从哪来"，不是"最近什么时候跑过"。
        self.assertEqual(row.source_batch_id, 'intraday-batch')

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

    def test_refresh_writes_nothing_when_the_snapshot_has_not_moved(self):
        self._store_previous_close(self.stock, '10.0')
        self._store_previous_close(self.other, '20.0')
        quotes = self._both_quotes()
        self._refresh(FakeSnapshotClient(quotes))
        rows_before = self._day_rows()

        result = self._refresh(FakeSnapshotClient(quotes))

        self.assertFalse(result.published)
        self.assertTrue(result.is_up_to_date)
        self.assertEqual(result.changed_record_count, 0)
        self.assertEqual(self._day_rows(), rows_before)

    def test_refresh_rejects_a_truncated_snapshot_without_writing_anything(self):
        self._store_previous_close(self.stock, '10.0')
        self._store_previous_close(self.other, '20.0')

        client = FakeSnapshotClient((_quote(self.stock.thscode, '000001', '11.0'),))
        # 阈值来自 .env；本用例断言的是"覆盖率不足必须整次拒绝"这条行为，
        # 所以把阈值固定在用例里，避免本机配置不同就让结果变色。
        with patch.dict(os.environ, {'INTRADAY_QUOTE_MIN_COVERAGE_RATIO': '0.9'}):
            with self.assertRaises(ValueError):
                self._refresh(client)

        self.assertEqual(self._day_rows(), {})

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
        self.assertEqual(self._day_rows(), {})

    def test_refresh_rejects_a_non_trading_day(self):
        client = FakeSnapshotClient(self._both_quotes())

        with self.assertRaises(ValueError):
            refresh_intraday_daily_prices(
                trade_date=date(2026, 9, 12), client=client
            )

        self.assertEqual(client.calls, [])

    def test_the_command_has_no_date_option(self):
        """日期不可指定：快照端点没有日期参数，它永远回答"此刻"。

        留着 ``--date`` 就等于留着一个能把今天的行情写到别的日期上的入口 ——
        业务日期恒为上海时区的今天，由 ``_now()`` 同时供业务日期和时段闸门使用。
        """
        parser = Command().create_parser('manage.py', 'refresh_intraday_quotes')

        self.assertEqual(
            {action.dest for action in parser._actions} & {'date', 'latest'},
            {'latest'},
        )

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
            patch(
                'core.management.commands.refresh_intraday_quotes._now',
                return_value=self._at(self.day, 10, 0),
            ),
        ):
            output = StringIO()
            call_command('refresh_intraday_quotes', stdout=output)

        self.assertIn(
            f'refreshed 2 intraday records (0 unchanged) for {self.day.isoformat()}',
            output.getvalue(),
        )

    def test_refresh_command_skips_a_non_trading_day_even_with_latest(self):
        """休市日连 --latest 也不取数：快照只会回答上一交易日的收盘态。

        这与 ``fetch_kaipanla_sector_fund_flow`` 刻意不同 —— 那条命令的 ``--latest``
        允许在非交易日强制采集，因为它采的是"最近一个交易日的收盘快照"这个明确的
        概念；而这里没有日期可以落，写下去就是把旧数据冒充成今天。
        """
        client = FakeSnapshotClient(self._both_quotes())

        for extra in ((), ('--latest',)):
            with self.subTest(args=extra):
                with (
                    patch(
                        'core.services.sync_daily_prices.HithinkClient',
                        return_value=client,
                    ),
                    patch(
                        'core.management.commands.refresh_intraday_quotes._now',
                        return_value=self._at(_NON_TRADING_DAY, 16, 0),
                    ),
                ):
                    output = StringIO()
                    call_command('refresh_intraday_quotes', *extra, stdout=output)

                rendered = output.getvalue()
                self.assertIn('skipped:', rendered)
                self.assertIn('is not a trading day', rendered)

        self.assertEqual(client.calls, [])
        self.assertFalse(DailyPrice.objects.filter(trade_date=_NON_TRADING_DAY).exists())

    def test_refresh_command_skips_outside_the_session_unless_latest_is_passed(self):
        self._store_previous_close(self.stock, '10.0')
        self._store_previous_close(self.other, '20.0')
        client = FakeSnapshotClient(self._both_quotes())
        closed = self._at(self.day, 16, 0)

        with (
            patch('core.services.sync_daily_prices.HithinkClient', return_value=client),
            patch(
                'core.services.sync_daily_prices._intraday_quote_page_size',
                return_value=2,
            ),
            patch(
                'core.management.commands.refresh_intraday_quotes._now',
                return_value=closed,
            ),
        ):
            output = StringIO()
            call_command('refresh_intraday_quotes', stdout=output)

            self.assertIn('skipped:', output.getvalue())
            self.assertEqual(client.calls, [])
            self.assertEqual(self._day_rows(), {})

            output = StringIO()
            call_command('refresh_intraday_quotes', '--latest', stdout=output)

        self.assertIn('refreshed 2 intraday records', output.getvalue())
        self.assertEqual(len(self._day_rows()), 2)

    def test_refresh_command_targets_today_in_shanghai(self):
        """业务日期来自命令自己的时钟，而不是运行环境的时区。"""
        self._store_previous_close(self.stock, '10.0')
        self._store_previous_close(self.other, '20.0')
        client = FakeSnapshotClient(self._both_quotes())

        with (
            patch('core.services.sync_daily_prices.HithinkClient', return_value=client),
            patch(
                'core.services.sync_daily_prices._intraday_quote_page_size',
                return_value=2,
            ),
            patch(
                'core.management.commands.refresh_intraday_quotes._now',
                return_value=self._at(self.day, 9, 30),
            ),
        ):
            call_command('refresh_intraday_quotes')

        self.assertEqual(
            DailyPrice.objects.filter(trade_date=self.day).count(), 2
        )

    def test_refresh_reports_upstream_failure_as_a_command_error_and_keeps_the_day(self):
        self._store_previous_close(self.stock, '10.0')
        self._store_previous_close(self.other, '20.0')
        DailyPrice.objects.create(
            stock=self.stock,
            trade_date=self.day,
            close_price=Decimal('10.5'),
            has_valid_trade=True,
            source_batch_id='intraday-batch',
        )
        before = self._day_rows()
        client = FakeSnapshotClient(error=HithinkUnavailableError('down'))

        with (
            patch('core.services.sync_daily_prices.HithinkClient', return_value=client),
            patch(
                'core.management.commands.refresh_intraday_quotes._now',
                return_value=self._at(self.day, 10, 0),
            ),
            self.assertLogs('core.management', level='ERROR') as captured,
            self.assertRaises(CommandError),
        ):
            call_command('refresh_intraday_quotes')

        # 失败只留日志，当天已有的行一行都不动。
        self.assertEqual(self._day_rows(), before)
        logged = '\n'.join(captured.output)
        self.assertIn('data_command_failed', logged)
        self.assertIn('dataset=stock_daily_prices', logged)
