import json
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from core.integrations.hithink.contracts import HithinkPriceBar, HithinkUnavailableError
from core.integrations.hithink.mappers import map_price_bar
from core.models import DailyPrice, DataVersion, ModuleRunStatus, Stock, TradingDay


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
        for trade_date in (self.first_day, self.second_day, self.last_day):
            TradingDay.objects.create(trade_date=trade_date)
        self.stock = Stock.objects.create(
            thscode='000001.SZ',
            stock_code='000001',
            stock_name='平安银行',
            exchange=Stock.Exchange.SZSE,
        )

    @contextmanager
    def _init_environment(self, client):
        """Patch the upstream client and the window end for the init command."""
        with (
            patch('core.services.sync_daily_prices.HithinkClient', return_value=client),
            patch(
                'core.services.sync_daily_prices.latest_eligible_trading_day',
                return_value=self.last_day,
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

    def test_initialization_creates_one_complete_version_per_recent_year_trading_day(self):
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
        versions = DataVersion.objects.filter(dataset_key='stock_daily_prices')
        self.assertEqual(versions.count(), 3)
        self.assertTrue(all(version.status == DataVersion.Status.COMPLETE for version in versions))
        self.assertEqual(
            set(versions.values_list('business_date', flat=True)),
            {self.first_day, self.second_day, self.last_day},
        )

    def test_initialization_revises_existing_rows_instead_of_refusing_to_run(self):
        """已存在数据不再是错误：改为逐条比对、只写有差异的行。"""
        DailyPrice.objects.create(
            stock=self.stock,
            trade_date=self.first_day,
            close_price=Decimal('9.9'),
            has_valid_trade=True,
            source_batch_id='existing-batch',
            source_data_version='existing-version',
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
        self.assertNotEqual(revised.source_data_version, 'existing-version')
        self.assertEqual(
            DataVersion.objects.filter(dataset_key='stock_daily_prices').count(),
            3,
        )

    def test_initialization_publishes_nothing_when_upstream_is_unchanged(self):
        """没有差异时不能发布新版本，否则下游会因为 source version 变化而全量重建。"""
        client = self._three_day_client()
        with self._init_environment(client):
            call_command('init_stock_daily_prices', '--years', '1')

        versions_before = dict(DailyPrice.objects.values_list('trade_date', 'source_data_version'))
        batches_before = set(DailyPrice.objects.values_list('source_batch_id', flat=True))
        version_count = DataVersion.objects.count()
        self.assertEqual(version_count, 3)

        with self._init_environment(client):
            output = StringIO()
            call_command('init_stock_daily_prices', '--years', '1', stdout=output)

        self.assertIn('no changes', output.getvalue())
        self.assertEqual(DataVersion.objects.count(), version_count)
        self.assertEqual(
            dict(DailyPrice.objects.values_list('trade_date', 'source_data_version')),
            versions_before,
        )
        self.assertEqual(
            set(DailyPrice.objects.values_list('source_batch_id', flat=True)),
            batches_before,
        )
        self.assertEqual(DailyPrice.objects.count(), 3)

    def test_initialization_updates_only_the_trading_day_that_changed(self):
        """修订历史只影响真正变化的交易日，且该交易日整体改归属新版本。"""
        with self._init_environment(self._three_day_client()):
            call_command('init_stock_daily_prices', '--years', '1')

        unaffected = {
            row.trade_date: row.source_data_version
            for row in DailyPrice.objects.exclude(trade_date=self.last_day)
        }

        # 只改最后一天的收盘价：它是链尾，不影响任何其他交易日的 pre_close/涨跌幅。
        with self._init_environment(self._three_day_client(closes=('10.1', '10.3', '10.9'))):
            output = StringIO()
            call_command('init_stock_daily_prices', '--years', '1', stdout=output)

        self.assertIn('updated 1 of 3 daily-price records across 1 trading days', output.getvalue())
        revised = DailyPrice.objects.get(stock=self.stock, trade_date=self.last_day)
        self.assertEqual(revised.close_price, Decimal('10.9000'))
        new_version = revised.source_data_version
        self.assertNotEqual(new_version, unaffected[self.second_day])
        self.assertEqual(
            set(
                DailyPrice.objects.filter(trade_date=self.last_day).values_list(
                    'source_data_version', flat=True
                )
            ),
            {new_version},
        )
        versions = DataVersion.objects.filter(
            dataset_key='stock_daily_prices',
            business_date=self.last_day,
        )
        self.assertEqual(versions.count(), 2)
        self.assertTrue(all(version.status == DataVersion.Status.COMPLETE for version in versions))
        covered = versions.get(version=new_version)
        self.assertEqual(covered.actual_record_count, 1)
        self.assertEqual(covered.expected_record_count, 1)
        # 被替换掉的那个版本仍然是 complete（运行确实成功了，这是历史），但它已经
        # 不持有任何一行 —— 行都改挂到新版本上了。计数要跟着说实话，否则管理页里
        # 同一个交易日会有两个"完整且满行"的版本，看不出在读哪个。
        replaced = versions.exclude(version=new_version).get()
        self.assertEqual(replaced.status, DataVersion.Status.COMPLETE)
        self.assertEqual(replaced.expected_record_count, 0)
        self.assertEqual(replaced.actual_record_count, 0)
        self.assertEqual(replaced.missing_record_count, 0)
        for trade_date, version in unaffected.items():
            self.assertEqual(
                DailyPrice.objects.get(stock=self.stock, trade_date=trade_date).source_data_version,
                version,
            )

    def test_initialization_fills_a_gap_left_by_an_interrupted_import(self):
        """中断后重跑应该补齐缺失的日期，而不是只修订已有行。"""
        partial = FakeHithinkClient({
            self.stock.thscode: (_bar(self.first_day, '10.1'),),
        })
        with patch('core.services.sync_daily_prices.HithinkClient', return_value=partial):
            call_command('sync_stock_daily_prices', '--date', self.first_day.isoformat())

        first_version = DailyPrice.objects.get(
            stock=self.stock, trade_date=self.first_day
        ).source_data_version

        with self._init_environment(self._three_day_client()):
            output = StringIO()
            call_command('init_stock_daily_prices', '--years', '1', stdout=output)

        self.assertIn('updated 2 of 3 daily-price records across 2 trading days', output.getvalue())
        self.assertEqual(DailyPrice.objects.filter(stock=self.stock).count(), 3)
        self.assertEqual(
            DailyPrice.objects.get(stock=self.stock, trade_date=self.first_day).source_data_version,
            first_version,
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
            source_data_version='old-version',
        )

        with self._init_environment(self._three_day_client()):
            output = StringIO()
            call_command('init_stock_daily_prices', '--years', '1', '--dry-run', stdout=output)

        self.assertIn('would update 3 of 3 daily-price records', output.getvalue())
        self.assertEqual(DailyPrice.objects.count(), 1)
        self.assertEqual(
            DailyPrice.objects.get(stock=self.stock, trade_date=self.last_day).source_data_version,
            'old-version',
        )
        self.assertEqual(DataVersion.objects.count(), 0)
        self.assertEqual(ModuleRunStatus.objects.count(), 0)

    def test_daily_sync_replaces_only_requested_date_and_is_idempotent(self):
        prior_day = date(2026, 9, 7)
        TradingDay.objects.create(trade_date=prior_day)
        DailyPrice.objects.create(
            stock=self.stock,
            trade_date=prior_day,
            close_price=Decimal('10.0'),
            has_valid_trade=True,
            source_batch_id='prior-batch',
            source_data_version='prior-version',
        )
        DataVersion.objects.create(
            dataset_key='stock_daily_prices',
            version='prior-version',
            business_date=prior_day,
            status=DataVersion.Status.COMPLETE,
            expected_record_count=1,
            actual_record_count=1,
        )
        client = FakeHithinkClient({
            self.stock.thscode: (
                HithinkPriceBar(
                    trade_date=self.last_day,
                    open_price=Decimal('10.1'),
                    high_price=Decimal('10.3'),
                    low_price=Decimal('10.0'),
                    close_price=Decimal('10.2'),
                    volume=1000,
                    turnover=Decimal('10200'),
                ),
            ),
        })

        with patch('core.services.sync_daily_prices.HithinkClient', return_value=client):
            call_command('sync_stock_daily_prices', '--date', self.last_day.isoformat())
            call_command('sync_stock_daily_prices', '--date', self.last_day.isoformat())

        self.assertEqual(
            client.calls,
            [
                (self.stock.thscode, self.last_day, self.last_day),
                (self.stock.thscode, self.last_day, self.last_day),
            ],
        )
        self.assertEqual(DailyPrice.objects.filter(stock=self.stock).count(), 2)
        price = DailyPrice.objects.get(stock=self.stock, trade_date=self.last_day)
        self.assertEqual(price.pre_close, Decimal('10.0000'))
        self.assertEqual(price.change_percent, Decimal('2.000000'))
        self.assertTrue(price.has_valid_trade)
        current_versions = DataVersion.objects.filter(
            dataset_key='stock_daily_prices',
            business_date=self.last_day,
        )
        self.assertEqual(current_versions.count(), 2)
        self.assertTrue(
            all(version.status == DataVersion.Status.COMPLETE for version in current_versions)
        )

    def test_daily_sync_dry_run_validates_without_writing_data_versions_or_status(self):
        client = FakeHithinkClient({
            self.stock.thscode: (
                HithinkPriceBar(
                    trade_date=self.last_day,
                    open_price=Decimal('10.0'),
                    high_price=Decimal('10.1'),
                    low_price=Decimal('9.9'),
                    close_price=Decimal('10.0'),
                    volume=1000,
                    turnover=Decimal('10000'),
                ),
            ),
        })

        with patch('core.services.sync_daily_prices.HithinkClient', return_value=client):
            output = StringIO()
            call_command(
                'sync_stock_daily_prices',
                '--date',
                self.last_day.isoformat(),
                '--dry-run',
                stdout=output,
            )

        self.assertIn('dry-run', output.getvalue())
        self.assertEqual(client.calls, [(self.stock.thscode, self.last_day, self.last_day)])
        self.assertEqual(DailyPrice.objects.count(), 0)
        self.assertEqual(DataVersion.objects.count(), 0)
        self.assertEqual(ModuleRunStatus.objects.count(), 0)

    def test_failed_daily_sync_preserves_the_existing_complete_version_and_prices(self):
        DailyPrice.objects.create(
            stock=self.stock,
            trade_date=self.last_day,
            close_price=Decimal('9.9'),
            has_valid_trade=True,
            source_batch_id='old-batch',
            source_data_version='old-version',
        )
        DataVersion.objects.create(
            dataset_key='stock_daily_prices',
            version='old-version',
            business_date=self.last_day,
            status=DataVersion.Status.COMPLETE,
            expected_record_count=1,
            actual_record_count=1,
        )
        client = FakeHithinkClient({
            self.stock.thscode: HithinkUnavailableError('upstream unavailable'),
        })

        with patch('core.services.sync_daily_prices.HithinkClient', return_value=client):
            with self.assertRaises(CommandError):
                call_command('sync_stock_daily_prices', '--date', self.last_day.isoformat())

        old_price = DailyPrice.objects.get(stock=self.stock, trade_date=self.last_day)
        self.assertEqual(old_price.close_price, Decimal('9.9000'))
        self.assertEqual(old_price.source_data_version, 'old-version')
        versions = DataVersion.objects.filter(
            dataset_key='stock_daily_prices',
            business_date=self.last_day,
        )
        self.assertEqual(versions.count(), 2)
        self.assertTrue(versions.filter(version='old-version', status=DataVersion.Status.COMPLETE).exists())
        self.assertTrue(versions.filter(status=DataVersion.Status.FAILED).exists())

    def test_failed_initialization_writes_no_prices_and_records_the_failure(self):
        """失败发生在发布之前，所以不会留下半成品版本，但运行状态仍要记失败。"""
        client = FakeHithinkClient({
            self.stock.thscode: HithinkUnavailableError('upstream unavailable'),
        })

        with self._init_environment(client):
            with self.assertRaises(CommandError):
                call_command('init_stock_daily_prices', '--years', '1')

        self.assertEqual(DailyPrice.objects.count(), 0)
        self.assertEqual(DataVersion.objects.count(), 0)
        status = ModuleRunStatus.objects.get(
            module_id='core',
            dataset_key='stock_daily_prices',
        )
        self.assertEqual(status.status, ModuleRunStatus.Status.FAILED)
        self.assertEqual(status.consecutive_failure_count, 1)

    def test_initialization_dry_run_failure_does_not_change_the_run_status(self):
        client = FakeHithinkClient({
            self.stock.thscode: HithinkUnavailableError('upstream unavailable'),
        })

        with self._init_environment(client):
            with self.assertRaises(CommandError):
                call_command('init_stock_daily_prices', '--years', '1', '--dry-run')

        self.assertEqual(DailyPrice.objects.count(), 0)
        self.assertEqual(DataVersion.objects.count(), 0)
        self.assertEqual(ModuleRunStatus.objects.count(), 0)

    def test_empty_stock_response_is_stored_as_a_non_trading_record(self):
        traded_stock = Stock.objects.create(
            thscode='600000.SH',
            stock_code='600000',
            stock_name='浦发银行',
            exchange=Stock.Exchange.SSE,
        )
        client = FakeHithinkClient({
            self.stock.thscode: (),
            traded_stock.thscode: (
                HithinkPriceBar(
                    trade_date=self.last_day,
                    open_price=Decimal('10.0'),
                    high_price=Decimal('10.1'),
                    low_price=Decimal('9.9'),
                    close_price=Decimal('10.0'),
                    volume=1000,
                    turnover=Decimal('10000'),
                ),
            ),
        })

        with patch('core.services.sync_daily_prices.HithinkClient', return_value=client):
            call_command('sync_stock_daily_prices', '--date', self.last_day.isoformat())

        price = DailyPrice.objects.get(stock=self.stock, trade_date=self.last_day)
        self.assertFalse(price.has_valid_trade)
        self.assertIsNone(price.close_price)
        self.assertIsNone(price.pre_close)
        version = DataVersion.objects.get(dataset_key='stock_daily_prices')
        self.assertEqual(version.status, DataVersion.Status.COMPLETE)
        self.assertEqual(version.expected_record_count, 2)
        self.assertEqual(version.actual_record_count, 2)
        self.assertEqual(version.missing_record_count, 0)

    def test_initialization_dry_run_does_not_write_prices_versions_or_status(self):
        client = self._three_day_client()

        with self._init_environment(client):
            call_command('init_stock_daily_prices', '--years', '1', '--dry-run')

        self.assertEqual(DailyPrice.objects.count(), 0)
        self.assertEqual(DataVersion.objects.count(), 0)
        self.assertEqual(ModuleRunStatus.objects.count(), 0)

    def test_daily_sync_rejects_an_empty_market_response_without_replacing_data(self):
        DailyPrice.objects.create(
            stock=self.stock,
            trade_date=self.last_day,
            close_price=Decimal('9.9'),
            has_valid_trade=True,
            source_batch_id='old-batch',
            source_data_version='old-version',
        )
        DataVersion.objects.create(
            dataset_key='stock_daily_prices',
            version='old-version',
            business_date=self.last_day,
            status=DataVersion.Status.COMPLETE,
            expected_record_count=1,
            actual_record_count=1,
        )
        client = FakeHithinkClient({self.stock.thscode: ()})

        with patch('core.services.sync_daily_prices.HithinkClient', return_value=client):
            with self.assertRaises(CommandError):
                call_command('sync_stock_daily_prices', '--date', self.last_day.isoformat())

        old_price = DailyPrice.objects.get(stock=self.stock, trade_date=self.last_day)
        self.assertEqual(old_price.source_data_version, 'old-version')
        versions = DataVersion.objects.filter(
            dataset_key='stock_daily_prices',
            business_date=self.last_day,
        )
        self.assertEqual(versions.count(), 2)
        self.assertTrue(versions.filter(status=DataVersion.Status.FAILED).exists())

    def test_hithink_daily_price_fixture_has_the_supported_raw_fields(self):
        fixture_path = Path(__file__).with_name('fixtures') / 'hithink_daily_prices.json'
        payload = json.loads(fixture_path.read_text())

        price = map_price_bar(payload['data']['item'][0])

        self.assertEqual(price.trade_date, self.first_day)
        self.assertEqual(price.close_price, Decimal('10.1'))
        self.assertEqual(price.volume, 1000)
        self.assertEqual(price.turnover, Decimal('10100'))


class BeginPublicationRunsTests(TestCase):
    """`_begin_runs` 要么给出全部运行记录，要么自己把已建的那几条收成失败。

    原来的写法 `tuple(begin_publication(...) for ...)` 在中途抛错时会留下已提交
    的 RUNNING 版本，而调用方的清理只会遍历一个空元组 —— 一年份的 init 会批量
    制造这种孤儿。
    """

    def setUp(self):
        self.days = (date(2025, 9, 8), date(2025, 9, 9), date(2025, 9, 10))

    def test_success_returns_one_run_per_day_with_its_coverage_window(self):
        from core.services import sync_daily_prices

        runs = sync_daily_prices._begin_runs(self.days, 10)

        self.assertEqual([run.business_date for run in runs], list(self.days))
        self.assertEqual(
            DataVersion.objects.filter(status=DataVersion.Status.RUNNING).count(), 3
        )
        for run in runs:
            version = DataVersion.objects.get(version=run.version)
            self.assertEqual(version.coverage_start_date, run.business_date)
            self.assertEqual(version.coverage_end_date, run.business_date)
            self.assertEqual(version.expected_record_count, 10)

    def test_a_failure_halfway_leaves_no_running_version_behind(self):
        from core.services import sync_daily_prices

        real_begin = sync_daily_prices.begin_publication
        started: list[date] = []

        def failing_begin(module_id, dataset_key, business_date, expected_record_count):
            if len(started) == 2:
                raise RuntimeError('database is locked')
            started.append(business_date)
            return real_begin(
                module_id, dataset_key, business_date, expected_record_count
            )

        with patch.object(
            sync_daily_prices, 'begin_publication', side_effect=failing_begin
        ):
            with self.assertRaises(RuntimeError):
                sync_daily_prices._begin_runs(self.days, 10)

        # 已经开始的两次必须在函数内收成 failed，不能留给调用方（它拿不到它们）。
        self.assertEqual(
            DataVersion.objects.filter(status=DataVersion.Status.RUNNING).count(), 0
        )
        failed = DataVersion.objects.filter(status=DataVersion.Status.FAILED)
        self.assertEqual(failed.count(), 2)
        self.assertEqual(
            sorted(DataVersion.objects.values_list('business_date', flat=True)),
            sorted(started),
        )
        for version in failed:
            self.assertIn('database is locked', version.error_summary)
            self.assertIsNotNone(version.finished_at)

    def test_a_failure_on_the_first_day_leaves_nothing_behind(self):
        from core.services import sync_daily_prices

        def always_fails(*args, **kwargs):
            raise RuntimeError('nope')

        with patch.object(
            sync_daily_prices, 'begin_publication', side_effect=always_fails
        ):
            with self.assertRaises(RuntimeError):
                sync_daily_prices._begin_runs(self.days, 10)

        self.assertEqual(DataVersion.objects.count(), 0)
