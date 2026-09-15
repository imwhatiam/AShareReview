import json
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from core.integrations.hithink.contracts import HithinkPriceBar, HithinkUnavailableError
from core.integrations.hithink.mappers import map_price_bar
from core.models import DailyPrice, Stock


_COMMAND_LOGGER = 'core.management'
# 比对用的业务字段：这些是「这份行情到底是什么」的全部内容。版本表删掉之后，
# 断言只能落在这些字段与 source_batch_id 上。
_COMPARED_FIELDS = (
    'pre_close',
    'open_price',
    'high_price',
    'low_price',
    'close_price',
    'change_percent',
    'volume',
    'turnover',
    'has_valid_trade',
)


def _stored_rows() -> dict[date, tuple]:
    return {
        row.trade_date: tuple(
            getattr(row, name) for name in _COMPARED_FIELDS
        ) + (row.source_batch_id,)
        for row in DailyPrice.objects.order_by('trade_date')
    }


class FakeHithinkClient:
    def __init__(self, prices_by_thscode):
        self.prices_by_thscode = prices_by_thscode
        self.calls = []

    def get_historical_prices(self, thscode, *, start_date, end_date):
        self.calls.append((thscode, start_date, end_date))
        result = self.prices_by_thscode[thscode]
        if isinstance(result, Exception):
            raise result
        return result


def _bar(trade_date, close):
    """Build a bar whose OHLC are all ``close``, so tests only vary one number."""
    close_price = Decimal(close)
    return HithinkPriceBar(
        trade_date=trade_date,
        open_price=close_price,
        high_price=close_price,
        low_price=close_price,
        close_price=close_price,
        volume=1000,
        turnover=close_price * 1000,
    )


class StockDailyPriceCommandTests(TestCase):
    def setUp(self):
        self.first_day = date(2025, 9, 8)
        self.second_day = date(2025, 9, 9)
        self.last_day = date(2026, 9, 8)
        self.stock = Stock.objects.create(
            thscode='000001.SZ',
            stock_code='000001',
            stock_name='平安银行',
            exchange=Stock.Exchange.SZSE,
        )

    @contextmanager
    def _init_environment(self, client):
        """Patch the upstream client and pin the init window to the three fixtures.

        The command derives its window from ``chinese-calendar`` (a real year is
        ~242 trading days). These cases are about revision/idempotence, not
        window size, so the range is pinned to the three fixture days —
        otherwise the market-coverage check would demand a bar for every real
        trading day in the year.
        """
        with (
            patch('core.services.sync_daily_prices.HithinkClient', return_value=client),
            patch(
                'core.services.sync_daily_prices.latest_eligible_trading_day',
                return_value=self.last_day,
            ),
            patch(
                'core.services.calendar.trading_days_between',
                return_value=(self.first_day, self.second_day, self.last_day),
            ),
        ):
            yield

    def _three_day_client(self, closes=('10.1', '10.3', '10.5')):
        return FakeHithinkClient({
            self.stock.thscode: tuple(
                _bar(trade_date, close)
                for trade_date, close in zip(
                    (self.first_day, self.second_day, self.last_day), closes, strict=True
                )
            ),
        })

    def test_initialization_writes_one_row_per_recent_year_trading_day(self):
        client = self._three_day_client()

        with self._init_environment(client):
            output = StringIO()
            call_command('init_stock_daily_prices', '--years', '1', stdout=output)

        self.assertIn('initialized 3 trading days', output.getvalue())
        self.assertEqual(client.calls, [(self.stock.thscode, self.first_day, self.last_day)])
        self.assertEqual(DailyPrice.objects.count(), 3)
        latest_price = DailyPrice.objects.get(stock=self.stock, trade_date=self.last_day)
        self.assertTrue(latest_price.has_valid_trade)
        self.assertEqual(latest_price.pre_close, Decimal('10.3000'))
        self.assertEqual(latest_price.change_percent, Decimal('1.941748'))
        # 一次初始化就是一个批次：三行都由这一批次写下，批次身份是「这份数据从哪来」
        # 的唯一记录 —— 版本表删掉之后不再有别的落点。
        batches = {row.source_batch_id for row in DailyPrice.objects.all()}
        self.assertEqual(len(batches), 1)
        self.assertTrue(next(iter(batches)))

    def test_initialization_revises_existing_rows_without_restamping_their_batch(self):
        """已存在数据不再是错误：改为逐条比对、只写有差异的行。"""
        DailyPrice.objects.create(
            stock=self.stock,
            trade_date=self.first_day,
            close_price=Decimal('9.9'),
            has_valid_trade=True,
            source_batch_id='existing-batch',
        )
        client = self._three_day_client()

        with self._init_environment(client):
            output = StringIO()
            call_command('init_stock_daily_prices', '--years', '1', stdout=output)

        self.assertNotIn('already exist', output.getvalue())
        self.assertIn('updated 3 of 3 daily-price records across 3 trading days', output.getvalue())
        self.assertEqual(DailyPrice.objects.count(), 3)
        revised = DailyPrice.objects.get(stock=self.stock, trade_date=self.first_day)
        self.assertEqual(revised.close_price, Decimal('10.1000'))
        self.assertEqual(revised.volume, 1000)
        # 业务字段被改写，但批次身份仍指向最早写下这行的那次运行：重跑不重盖，
        # 因为它回答的是"这行从哪来"，而不是"最近一次跑是什么时候"。
        self.assertEqual(revised.source_batch_id, 'existing-batch')

    def test_initialization_writes_nothing_when_upstream_is_unchanged(self):
        """与上游逐条一致时不写：重写内容相同的行只会无端改动落库时刻。"""
        client = self._three_day_client()
        with self._init_environment(client):
            call_command('init_stock_daily_prices', '--years', '1')

        rows_before = _stored_rows()
        self.assertEqual(len(rows_before), 3)

        with self._init_environment(client):
            output = StringIO()
            call_command('init_stock_daily_prices', '--years', '1', stdout=output)

        self.assertIn('no changes', output.getvalue())
        self.assertEqual(_stored_rows(), rows_before)
        self.assertEqual(DailyPrice.objects.count(), 3)

    def test_initialization_updates_only_the_trading_day_that_changed(self):
        """修订历史只影响真正变化的交易日，其余行逐字段原样保留。"""
        with self._init_environment(self._three_day_client()):
            call_command('init_stock_daily_prices', '--years', '1')

        unaffected = {
            trade_date: values
            for trade_date, values in _stored_rows().items()
            if trade_date != self.last_day
        }

        # 只改最后一天的收盘价：它是链尾，不影响任何其他交易日的 pre_close/涨跌幅。
        with self._init_environment(self._three_day_client(closes=('10.1', '10.3', '10.9'))):
            output = StringIO()
            call_command('init_stock_daily_prices', '--years', '1', stdout=output)

        self.assertIn('updated 1 of 3 daily-price records across 1 trading days', output.getvalue())
        revised = DailyPrice.objects.get(stock=self.stock, trade_date=self.last_day)
        self.assertEqual(revised.close_price, Decimal('10.9000'))
        after = _stored_rows()
        self.assertEqual(
            {day: values for day, values in after.items() if day != self.last_day},
            unaffected,
        )

    def test_initialization_fills_a_gap_left_by_an_interrupted_import(self):
        """中断后重跑应该补齐缺失的日期，而不是只修订已有行。"""
        # 只落下第一天，模拟一次中断的导入：这一行的业务字段与 init 会算出来的
        # 完全一致（首日没有前收，所以 pre_close/涨跌幅为空）。
        DailyPrice.objects.create(
            stock=self.stock,
            trade_date=self.first_day,
            open_price=Decimal('10.1'),
            high_price=Decimal('10.1'),
            low_price=Decimal('10.1'),
            close_price=Decimal('10.1'),
            volume=1000,
            turnover=Decimal('10100'),
            has_valid_trade=True,
            source_batch_id='partial-batch',
        )

        with self._init_environment(self._three_day_client()):
            output = StringIO()
            call_command('init_stock_daily_prices', '--years', '1', stdout=output)

        self.assertIn('updated 2 of 3 daily-price records across 2 trading days', output.getvalue())
        self.assertEqual(DailyPrice.objects.filter(stock=self.stock).count(), 3)
        # 第一天与上游一致，所以没被重写：批次身份没变。
        self.assertEqual(
            DailyPrice.objects.get(stock=self.stock, trade_date=self.first_day).source_batch_id,
            'partial-batch',
        )
        for trade_date in (self.second_day, self.last_day):
            self.assertTrue(
                DailyPrice.objects.get(stock=self.stock, trade_date=trade_date).has_valid_trade
            )

    def test_initialization_dry_run_reports_the_diff_without_writing(self):
        DailyPrice.objects.create(
            stock=self.stock,
            trade_date=self.last_day,
            close_price=Decimal('9.9'),
            has_valid_trade=True,
            source_batch_id='old-batch',
        )

        with self._init_environment(self._three_day_client()):
            output = StringIO()
            call_command('init_stock_daily_prices', '--years', '1', '--dry-run', stdout=output)

        self.assertIn('would update 3 of 3 daily-price records', output.getvalue())
        self.assertEqual(DailyPrice.objects.count(), 1)
        self.assertEqual(
            DailyPrice.objects.get(stock=self.stock, trade_date=self.last_day).close_price,
            Decimal('9.9000'),
        )

    def test_failed_initialization_writes_no_prices_and_logs_the_failure(self):
        """失败发生在写入之前，所以不会留下半成品；失败原因只落日志。"""
        client = FakeHithinkClient({
            self.stock.thscode: HithinkUnavailableError('upstream unavailable'),
        })

        with self._init_environment(client):
            with self.assertLogs(_COMMAND_LOGGER, level='ERROR') as captured:
                with self.assertRaises(CommandError):
                    call_command('init_stock_daily_prices', '--years', '1')

        self.assertEqual(DailyPrice.objects.count(), 0)
        self.assertIn('data_command_failed', '\n'.join(captured.output))

    def test_initialization_dry_run_failure_writes_nothing(self):
        client = FakeHithinkClient({
            self.stock.thscode: HithinkUnavailableError('upstream unavailable'),
        })

        with self._init_environment(client):
            with self.assertRaises(CommandError):
                call_command('init_stock_daily_prices', '--years', '1', '--dry-run')

        self.assertEqual(DailyPrice.objects.count(), 0)

    def test_a_stock_with_no_bars_still_gets_a_non_trading_row(self):
        """响应为空的股票同样落行：否则「今天没有它」与「今天停牌」分不开。"""
        traded_stock = Stock.objects.create(
            thscode='600000.SH',
            stock_code='600000',
            stock_name='浦发银行',
            exchange=Stock.Exchange.SSE,
        )
        client = FakeHithinkClient({
            self.stock.thscode: (),
            traded_stock.thscode: tuple(
                _bar(trade_date, close)
                for trade_date, close in zip(
                    (self.first_day, self.second_day, self.last_day),
                    ('10.0', '10.1', '10.0'),
                    strict=True,
                )
            ),
        })

        with self._init_environment(client):
            call_command('init_stock_daily_prices', '--years', '1')

        price = DailyPrice.objects.get(stock=self.stock, trade_date=self.last_day)
        self.assertFalse(price.has_valid_trade)
        self.assertIsNone(price.close_price)
        self.assertIsNone(price.pre_close)
        self.assertEqual(DailyPrice.objects.filter(trade_date=self.last_day).count(), 2)
        self.assertTrue(
            DailyPrice.objects.get(stock=traded_stock, trade_date=self.last_day).has_valid_trade
        )

    def test_initialization_dry_run_does_not_write_prices(self):
        client = self._three_day_client()

        with self._init_environment(client):
            call_command('init_stock_daily_prices', '--years', '1', '--dry-run')

        self.assertEqual(DailyPrice.objects.count(), 0)

    def test_hithink_daily_price_fixture_has_the_supported_raw_fields(self):
        fixture_path = Path(__file__).with_name('fixtures') / 'hithink_daily_prices.json'
        payload = json.loads(fixture_path.read_text())

        price = map_price_bar(payload['data']['item'][0])

        self.assertEqual(price.trade_date, self.first_day)
        self.assertEqual(price.close_price, Decimal('10.1'))
        self.assertEqual(price.volume, 1000)
        self.assertEqual(price.turnover, Decimal('10100'))
