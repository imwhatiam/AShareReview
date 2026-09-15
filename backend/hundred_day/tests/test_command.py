from datetime import date, timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from core.models import IndustrySnapshot
from core.services.contracts import Industry
from core.services.market_data import CompleteMarketDataUnavailable
from hundred_day.models import (
    HundredDayBreadth,
    HundredDayIndustrySummary,
    HundredDayStockFlag,
)
from hundred_day.services.analysis import (
    HistoricalCloseData,
    TargetDayQuote,
)

_COMMAND_LOGGER = 'core.management'
_SOURCE_DATA = 'hundred_day.management.commands.build_hundred_day.load_hundred_day_source_data'


class BuildHundredDayCommandTests(TestCase):
    databases = {'default', 'hundred_day'}
    business_date = date(2026, 9, 8)

    def setUp(self):
        # 行业归属决定板块汇总怎么分组，命令会先确认映射在库里。
        IndustrySnapshot.objects.create(
            industry_code='I001', industry_name='电子', stock_codes=['600001']
        )

    def _source(self, positions=100, business_date=None):
        day = business_date or self.business_date
        days = tuple(
            day - timedelta(days=positions - index - 1) for index in range(positions)
        )
        return HistoricalCloseData(
            business_date=day,
            trading_days=days,
            close_prices_by_stock={
                '600001': {value: Decimal('10') for value in days[:-1]}
                | {days[-1]: Decimal('11')},
            },
            stock_names_by_code={'600001': '上涨股票'},
            industries=(Industry('I001', '电子', ('600001',)),),
            target_day_quotes={'600001': TargetDayQuote(Decimal('10'), Decimal('1000000'))},
        )

    def _breadth(self, **filters):
        return HundredDayBreadth.objects.using('hundred_day').filter(**filters)

    @patch(_SOURCE_DATA)
    def test_writes_breadth_stock_and_industry_records_from_local_public_data(self, source):
        source.return_value = self._source()
        output = StringIO()

        call_command('build_hundred_day', '--date', '2026-09-08', stdout=output)

        # 100 个输入交易日只能评出最后一个（滚动窗口要 99 个前置位置），所以这次发布
        # 的市场宽度只有一个点，而它就是当日结果。
        point = self._breadth().get()
        self.assertEqual(point.business_date, self.business_date)
        self.assertEqual(point.trade_date, self.business_date)
        self.assertEqual(point.valid_stock_count, 1)
        self.assertEqual(point.new_high_count, 1)
        self.assertEqual(point.new_low_count, 0)
        self.assertEqual(HundredDayStockFlag.objects.using('hundred_day').count(), 1)
        # 行业汇总只留成分股数量；新高/新低数量是读时从个股标志算出来的。
        summary = HundredDayIndustrySummary.objects.using('hundred_day').get()
        self.assertEqual(summary.stock_count, 1)
        self.assertIn('built 1 hundred-day stock flags', output.getvalue())

    @patch(_SOURCE_DATA)
    def test_the_whole_window_is_published_as_the_trend(self, source):
        """趋势点与当日汇总同表：199 个输入交易日评出 100 个点，全都落库。"""
        source.return_value = self._source(positions=199)

        call_command('build_hundred_day', '--date', '2026-09-08')

        self.assertEqual(self._breadth().count(), 100)
        latest = self._breadth().order_by('trade_date').last()
        self.assertEqual(latest.trade_date, self.business_date)
        self.assertEqual(latest.valid_stock_count, 1)
        self.assertEqual(latest.new_high_count, 1)

    @patch(_SOURCE_DATA)
    def test_a_rebuild_replaces_the_days_rows_instead_of_adding_one(self, source):
        """同一天重跑是覆盖这一天的全部行 —— 结果按业务日期唯一，没有版本号可比。"""
        source.return_value = self._source(positions=199)

        call_command('build_hundred_day', '--date', '2026-09-08')
        call_command('build_hundred_day', '--date', '2026-09-08')

        self.assertEqual(self._breadth().count(), 100)
        self.assertEqual(HundredDayStockFlag.objects.using('hundred_day').count(), 1)
        self.assertEqual(HundredDayIndustrySummary.objects.using('hundred_day').count(), 1)

    @patch(_SOURCE_DATA)
    def test_a_rebuild_moves_published_at_forward(self, source):
        """重跑必须刷新发布时间 —— 它是文件缓存的缓存身份。

        不前进的话，重建之后页面在 TTL 内还会继续拿到上一版报文。
        """
        source.return_value = self._source()
        call_command('build_hundred_day', '--date', '2026-09-08')
        first = self._breadth().get().published_at

        call_command('build_hundred_day', '--date', '2026-09-08')
        second = self._breadth().get().published_at

        self.assertGreater(second, first)

    @patch(_SOURCE_DATA)
    def test_dry_run_does_not_write_results(self, source):
        source.return_value = self._source()

        call_command('build_hundred_day', '--date', '2026-09-08', '--dry-run')

        self.assertFalse(self._breadth().exists())
        self.assertFalse(HundredDayStockFlag.objects.using('hundred_day').exists())
        self.assertFalse(HundredDayIndustrySummary.objects.using('hundred_day').exists())

    @patch(_SOURCE_DATA)
    def test_missing_complete_local_public_data_writes_nothing_and_logs_the_failure(self, source):
        source.side_effect = CompleteMarketDataUnavailable('No daily prices are stored.')

        with self.assertLogs(_COMMAND_LOGGER, level='ERROR') as captured:
            with self.assertRaises(CommandError):
                call_command('build_hundred_day', '--date', '2026-09-08')

        self.assertFalse(self._breadth().exists())
        self.assertIn('data_command_failed', '\n'.join(captured.output))

    @patch(_SOURCE_DATA)
    def test_insufficient_history_writes_nothing_and_logs_the_failure(self, source):
        source.return_value = self._source(positions=99)

        with self.assertLogs(_COMMAND_LOGGER, level='ERROR') as captured:
            with self.assertRaises(CommandError) as caught:
                call_command('build_hundred_day', '--date', '2026-09-08')

        self.assertIn('requires at least 100', str(caught.exception))
        self.assertFalse(self._breadth().exists())
        self.assertIn('data_command_failed', '\n'.join(captured.output))

    @patch(_SOURCE_DATA)
    def test_missing_industry_mapping_fails_without_writing_a_result(self, source):
        """没有行业映射就没有板块分组：宁可失败，也不落一份空汇总的结果。"""
        IndustrySnapshot.objects.all().delete()
        source.return_value = self._source()

        with self.assertRaises(CommandError) as caught:
            call_command('build_hundred_day', '--date', '2026-09-08')

        self.assertIn('No Kaipanla industry snapshot is stored.', str(caught.exception))
        self.assertFalse(self._breadth().exists())
