from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from core.integrations.hithink.contracts import HithinkTicker, HithinkUnavailableError
from core.models import Stock


class FakeHithinkClient:
    def __init__(self, ticker_pages=(), error=None):
        self.ticker_pages = list(ticker_pages)
        self.error = error
        self.offsets = []

    def list_a_share_tickers(self, *, limit, offset):
        self.offsets.append(offset)
        if self.error:
            raise self.error
        return self.ticker_pages.pop(0) if self.ticker_pages else ()


class ReferenceSyncCommandTests(TestCase):
    """股票主数据同步：一次运行 = 一个事务。

    以前"这次同步成功了吗"由 ``DataVersion`` 与 ``ModuleRunStatus`` 两张表回答；
    现在只有两种可观察结果 —— 库里的行被整体替换，或者一行都没动。所以这里断言
    的重点从"版本行写了什么状态"变成了"失败之后旧数据是否原样还在"。
    """

    def test_stock_master_command_upserts_all_pages(self):
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

    def test_stock_master_dry_run_does_not_write_anything(self):
        client = FakeHithinkClient(ticker_pages=[
            (HithinkTicker('000001.SZ', '000001', '平安银行', 'szse'),),
            (),
        ])

        with patch('core.services.sync_reference.HithinkClient', return_value=client):
            output = StringIO()
            call_command('sync_stock_master', '--dry-run', stdout=output)

        self.assertIn('dry-run', output.getvalue())
        self.assertEqual(Stock.objects.count(), 0)

    def test_failed_stock_master_sync_keeps_previously_stored_data(self):
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

    def test_truncated_stock_master_list_is_rejected_without_deactivating_anything(self):
        """上游少返回若干页时，绝不能把没出现的股票静默停用（P0-2）。"""
        for index in range(10):
            Stock.objects.create(
                thscode=f'0000{index:02d}.SZ',
                stock_code=f'0000{index:02d}',
                stock_name=f'股票{index}',
                exchange=Stock.Exchange.SZSE,
            )
        partial = tuple(
            HithinkTicker(f'0000{index:02d}.SZ', f'0000{index:02d}', f'股票{index}', 'szse')
            for index in range(5)
        )
        client = FakeHithinkClient(ticker_pages=[partial, ()])

        with patch('core.services.sync_reference.HithinkClient', return_value=client):
            with self.assertRaises(CommandError):
                call_command('sync_stock_master', '--limit', '5')

        self.assertEqual(Stock.objects.filter(is_active=True).count(), 10)

    def test_stock_master_sync_tolerates_a_normal_deviation(self):
        """小幅波动（0.9 阈值内）照常写入：真退市是允许的。"""
        for index in range(10):
            Stock.objects.create(
                thscode=f'0000{index:02d}.SZ',
                stock_code=f'0000{index:02d}',
                stock_name=f'股票{index}',
                exchange=Stock.Exchange.SZSE,
            )
        remaining = tuple(
            HithinkTicker(f'0000{index:02d}.SZ', f'0000{index:02d}', f'股票{index}', 'szse')
            for index in range(9)
        )
        client = FakeHithinkClient(ticker_pages=[remaining, ()])

        with patch('core.services.sync_reference.HithinkClient', return_value=client):
            call_command('sync_stock_master', '--limit', '10')

        self.assertEqual(Stock.objects.filter(is_active=True).count(), 9)
        self.assertFalse(Stock.objects.get(stock_code='000009').is_active)

    def test_dry_run_also_reports_a_truncated_stock_master_list(self):
        for index in range(10):
            Stock.objects.create(
                thscode=f'0000{index:02d}.SZ',
                stock_code=f'0000{index:02d}',
                stock_name=f'股票{index}',
                exchange=Stock.Exchange.SZSE,
            )
        partial = (HithinkTicker('000000.SZ', '000000', '股票0', 'szse'),)
        client = FakeHithinkClient(ticker_pages=[partial, ()])

        with patch('core.services.sync_reference.HithinkClient', return_value=client):
            with self.assertRaises(CommandError):
                call_command('sync_stock_master', '--dry-run', '--limit', '5')

        self.assertEqual(Stock.objects.filter(is_active=True).count(), 10)
