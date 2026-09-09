from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from core.services.contracts import MarketDataVersion, ParentIndustry
from core.services.market_data import CompleteMarketDataUnavailable
from hundred_day.models import HundredDayResult
from hundred_day.services.analysis import HistoricalCloseData, InsufficientHundredDayHistory
from hundred_day.services.read_path import read_hundred_day


class HundredDayFallbackTests(TestCase):
    databases = {'default', 'hundred_day'}
    business_date = date(2026, 9, 8)

    def _source(self, positions=100):
        days = tuple(
            self.business_date - timedelta(days=positions - index - 1)
            for index in range(positions)
        )
        return HistoricalCloseData(
            data_version=MarketDataVersion('daily-prices-v2', self.business_date),
            trading_days=days,
            close_prices_by_stock={
                '600001': {day: Decimal('10') for day in days[:-1]} | {days[-1]: Decimal('11')}
            },
            stock_names_by_code={'600001': '测试股票'},
            parent_industries=(ParentIndustry('I001', '电子', ('600001',)),),
        )

    @patch('hundred_day.services.read_path.get_complete_industry_snapshot_version')
    @patch('hundred_day.services.read_path.load_hundred_day_source_data')
    @patch('hundred_day.services.read_path._max_local_repair_rows', return_value=100)
    def test_missing_result_is_rebuilt_only_from_small_local_source_data(self, _, source, industry_version):
        source.return_value = self._source()
        industry_version.return_value = 'industries-v2'

        result = read_hundred_day(self.business_date)

        self.assertEqual(result.source, 'computed')
        self.assertEqual(result.data_version, 'daily-prices-v2:industries-v2')
        self.assertTrue(HundredDayResult.objects.using('hundred_day').exists())

    @patch('hundred_day.services.read_path.load_hundred_day_source_data')
    @patch('hundred_day.services.read_path._max_local_repair_rows', return_value=1)
    def test_large_local_rebuild_is_refused_without_any_remote_sync(self, _, source):
        source.return_value = self._source()

        with self.assertRaises(CompleteMarketDataUnavailable):
            read_hundred_day(self.business_date)

    @patch('hundred_day.services.read_path.get_complete_industry_snapshot_version')
    @patch('hundred_day.services.read_path.load_hundred_day_source_data')
    @patch('hundred_day.services.read_path._max_local_repair_rows', return_value=100)
    def test_insufficient_history_propagates_instead_of_publishing_zero_result(
        self, _, source, industry_version
    ):
        source.return_value = self._source(positions=99)
        industry_version.return_value = 'industries-v1'

        with self.assertRaises(InsufficientHundredDayHistory):
            read_hundred_day(self.business_date)
