"""199 日滑窗的输入加载：日期与版本必须一一对上，不能混进别的版本的行。"""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from core.models import DailyPrice, DataVersion, Stock, TradingDay
from core.services.market_data import STOCK_DAILY_PRICES_DATASET
from hundred_day.services.source_data import load_hundred_day_source_data


class SourceDataVersionFilterTests(TestCase):
    databases = {'default'}

    def setUp(self):
        self.days = (date(2026, 9, 3), date(2026, 9, 4), date(2026, 9, 7))
        self.business_date = self.days[-1]
        TradingDay.objects.bulk_create([TradingDay(trade_date=day) for day in self.days])
        self.stock = Stock.objects.create(
            thscode='600001.SH', stock_code='600001', stock_name='测试股票', exchange='sse'
        )
        for index, day in enumerate(self.days):
            self._publish_day(day, version=f'prices-{day}', close=Decimal(10 + index))

    def _publish_day(self, day: date, *, version: str, close: Decimal) -> None:
        DataVersion.objects.create(
            dataset_key=STOCK_DAILY_PRICES_DATASET,
            version=version,
            business_date=day,
            status=DataVersion.Status.COMPLETE,
            expected_record_count=1,
            actual_record_count=1,
        )
        DailyPrice.objects.create(
            stock=self.stock,
            trade_date=day,
            close_price=close,
            has_valid_trade=True,
            source_batch_id='batch',
            source_data_version=version,
        )

    def test_every_day_contributes_its_own_version(self):
        data = load_hundred_day_source_data(self.business_date)

        self.assertEqual(
            data.close_prices_by_stock['600001'],
            {day: Decimal(10 + index) for index, day in enumerate(self.days)},
        )

    def test_a_row_left_on_an_older_version_is_not_part_of_the_window(self):
        """某天"改挂新版本"只跑了一半时，剩下的旧行不能参与滑窗极值。

        否则 199 日窗口会静默混入旧收盘价，而产物版本号完全看不出来。
        """
        stale_day = self.days[0]
        DailyPrice.objects.filter(trade_date=stale_day).update(
            source_data_version='prices-stale'
        )

        data = load_hundred_day_source_data(self.business_date)

        # 旧版本的行被排除：那一天对这个股票就没有记录，而不是悄悄用旧价。
        self.assertNotIn(stale_day, data.close_prices_by_stock['600001'])
        self.assertEqual(
            data.close_prices_by_stock['600001'],
            {self.days[1]: Decimal(11), self.days[2]: Decimal(12)},
        )
