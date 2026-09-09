from datetime import date
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from core.integrations.hithink.contracts import HithinkTicker, HithinkUnavailableError
from core.models import DataVersion, Stock, TradingDay


class FakeHithinkClient:
    def __init__(self, ticker_pages=(), trading_days=(), error=None):
        self.ticker_pages = list(ticker_pages)
        self.trading_days = trading_days
        self.error = error
        self.offsets = []

    def list_a_share_tickers(self, *, limit, offset):
        self.offsets.append(offset)
        if self.error:
            raise self.error
        return self.ticker_pages.pop(0) if self.ticker_pages else ()

    def list_trading_days(self):
        if self.error:
            raise self.error
        return self.trading_days


class ReferenceSyncCommandTests(TestCase):
    def test_stock_master_command_upserts_all_pages_and_publishes_complete_version(self):
        client = FakeHithinkClient(ticker_pages=[
            (
                HithinkTicker('000001.SZ', '000001', '平安银行', 'szse'),
                HithinkTicker('600000.SH', '600000', '浦发银行', 'sse'),
            ),
            (),
        ])

        with patch('core.services.sync_reference.HithinkClient', return_value=client):
            call_command('sync_stock_master', '--limit', '2')

        self.assertEqual(client.offsets, [0, 2])
        self.assertEqual(Stock.objects.count(), 2)
        self.assertEqual(Stock.objects.get(stock_code='000001').exchange, 'szse')
        version = DataVersion.objects.get(dataset_key='stock_master')
        self.assertEqual(version.status, DataVersion.Status.COMPLETE)
        self.assertEqual(version.expected_record_count, 2)
        self.assertEqual(version.actual_record_count, 2)

    def test_stock_master_dry_run_does_not_write_models_or_versions(self):
        client = FakeHithinkClient(ticker_pages=[
            (HithinkTicker('000001.SZ', '000001', '平安银行', 'szse'),),
            (),
        ])

        with patch('core.services.sync_reference.HithinkClient', return_value=client):
            output = StringIO()
            call_command('sync_stock_master', '--dry-run', stdout=output)

        self.assertIn('dry-run', output.getvalue())
        self.assertEqual(Stock.objects.count(), 0)
        self.assertEqual(DataVersion.objects.count(), 0)

    def test_failed_stock_master_sync_keeps_previously_published_data(self):
        Stock.objects.create(
            thscode='000001.SZ',
            stock_code='000001',
            stock_name='旧名称',
            exchange=Stock.Exchange.SZSE,
        )
        client = FakeHithinkClient(error=HithinkUnavailableError('unavailable'))

        with patch('core.services.sync_reference.HithinkClient', return_value=client):
            with self.assertRaises(CommandError):
                call_command('sync_stock_master')

        stock = Stock.objects.get(stock_code='000001')
        self.assertEqual(stock.stock_name, '旧名称')
        self.assertEqual(
            DataVersion.objects.get(dataset_key='stock_master').status,
            DataVersion.Status.FAILED,
        )

    def test_trading_calendar_command_replaces_the_recent_window_atomically(self):
        TradingDay.objects.create(trade_date=date(2025, 9, 8))
        client = FakeHithinkClient(trading_days=(
            date(2026, 9, 7),
            date(2026, 9, 8),
        ))

        with patch('core.services.sync_reference.HithinkClient', return_value=client):
            call_command('sync_trading_calendar')

        self.assertEqual(
            list(TradingDay.objects.values_list('trade_date', flat=True)),
            [date(2026, 9, 7), date(2026, 9, 8)],
        )
        version = DataVersion.objects.get(dataset_key='trading_calendar')
        self.assertEqual(version.status, DataVersion.Status.COMPLETE)
        self.assertEqual(version.business_date, date(2026, 9, 8))

    def test_invalid_trading_calendar_order_is_rejected_without_replacing_data(self):
        TradingDay.objects.create(trade_date=date(2026, 9, 7))
        client = FakeHithinkClient(trading_days=(
            date(2026, 9, 8),
            date(2026, 9, 7),
        ))

        with patch('core.services.sync_reference.HithinkClient', return_value=client):
            with self.assertRaises(CommandError):
                call_command('sync_trading_calendar')

        self.assertEqual(
            list(TradingDay.objects.values_list('trade_date', flat=True)),
            [date(2026, 9, 7)],
        )
        self.assertEqual(
            DataVersion.objects.get(dataset_key='trading_calendar').status,
            DataVersion.Status.FAILED,
        )
