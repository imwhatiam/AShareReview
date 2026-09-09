import json
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

    def test_initialization_creates_one_complete_version_per_recent_year_trading_day(self):
        client = FakeHithinkClient({
            self.stock.thscode: (
                HithinkPriceBar(
                    trade_date=self.first_day,
                    open_price=Decimal('10.0'),
                    high_price=Decimal('10.2'),
                    low_price=Decimal('9.9'),
                    close_price=Decimal('10.1'),
                    volume=1000,
                    turnover=Decimal('10100'),
                ),
                HithinkPriceBar(
                    trade_date=self.second_day,
                    open_price=Decimal('10.2'),
                    high_price=Decimal('10.4'),
                    low_price=Decimal('10.1'),
                    close_price=Decimal('10.3'),
                    volume=1200,
                    turnover=Decimal('12360'),
                ),
                HithinkPriceBar(
                    trade_date=self.last_day,
                    open_price=Decimal('10.4'),
                    high_price=Decimal('10.6'),
                    low_price=Decimal('10.3'),
                    close_price=Decimal('10.5'),
                    volume=1500,
                    turnover=Decimal('15750'),
                ),
            ),
        })

        with (
            patch('core.services.sync_daily_prices.HithinkClient', return_value=client),
            patch(
                'core.services.sync_daily_prices.latest_eligible_trading_day',
                return_value=self.last_day,
            ),
        ):
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

    def test_failed_initialization_writes_no_prices_and_marks_each_daily_version_failed(self):
        client = FakeHithinkClient({
            self.stock.thscode: HithinkUnavailableError('upstream unavailable'),
        })

        with (
            patch('core.services.sync_daily_prices.HithinkClient', return_value=client),
            patch(
                'core.services.sync_daily_prices.latest_eligible_trading_day',
                return_value=self.last_day,
            ),
        ):
            with self.assertRaises(CommandError):
                call_command('init_stock_daily_prices', '--years', '1')

        self.assertEqual(DailyPrice.objects.count(), 0)
        versions = DataVersion.objects.filter(dataset_key='stock_daily_prices')
        self.assertEqual(versions.count(), 3)
        self.assertTrue(all(version.status == DataVersion.Status.FAILED for version in versions))
        status = ModuleRunStatus.objects.get(
            module_id='core',
            dataset_key='stock_daily_prices',
        )
        self.assertEqual(status.consecutive_failure_count, 1)

    def test_initialization_refuses_to_run_again_after_prices_exist(self):
        DailyPrice.objects.create(
            stock=self.stock,
            trade_date=self.first_day,
            close_price=Decimal('10.0'),
            has_valid_trade=True,
            source_batch_id='existing-batch',
            source_data_version='existing-version',
        )

        with self.assertRaises(CommandError):
            call_command('init_stock_daily_prices', '--years', '1')

        self.assertEqual(DailyPrice.objects.count(), 1)
        self.assertEqual(DataVersion.objects.count(), 0)

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
        client = FakeHithinkClient({
            self.stock.thscode: tuple(
                HithinkPriceBar(
                    trade_date=trade_date,
                    open_price=Decimal('10.0'),
                    high_price=Decimal('10.1'),
                    low_price=Decimal('9.9'),
                    close_price=Decimal('10.0'),
                    volume=1000,
                    turnover=Decimal('10000'),
                )
                for trade_date in (self.first_day, self.second_day, self.last_day)
            ),
        })

        with (
            patch('core.services.sync_daily_prices.HithinkClient', return_value=client),
            patch(
                'core.services.sync_daily_prices.latest_eligible_trading_day',
                return_value=self.last_day,
            ),
        ):
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
