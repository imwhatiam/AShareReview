"""199 日滑窗的输入加载。

窗口本身来自 `chinese-calendar`（真实一年约 242 个交易日），所以这里把窗口长度
压到夹具的三天：本文件考的是"哪些行算进窗口"，不是窗口大小。

没有版本过滤了。公共日行情的唯一键是「股票 + 交易日」，同步命令对同一天是整批
upsert 覆盖，同一天不可能同时留着两套新旧不同的行，所以窗口只按交易日取数。
"""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from core.models import DailyPrice, Stock
from hundred_day.services.source_data import load_hundred_day_source_data


class SourceDataWindowTests(TestCase):
    databases = {'default'}

    def setUp(self):
        self.days = (date(2026, 9, 3), date(2026, 9, 4), date(2026, 9, 7))
        self.business_date = self.days[-1]
        self.stock = Stock.objects.create(
            thscode='600001.SH', stock_code='600001', stock_name='测试股票', exchange='sse'
        )
        for index, day in enumerate(self.days):
            self._store_day(day, close=Decimal(10 + index))

    def _load(self):
        with patch(
            'hundred_day.services.source_data.MAX_INPUT_TRADING_DAY_POSITIONS',
            len(self.days),
        ):
            return load_hundred_day_source_data(self.business_date)

    def _store_day(self, day: date, *, close: Decimal, has_valid_trade: bool = True) -> None:
        DailyPrice.objects.create(
            stock=self.stock,
            trade_date=day,
            close_price=close,
            has_valid_trade=has_valid_trade,
            source_batch_id='batch',
        )

    def test_every_day_in_the_window_contributes_its_own_close(self):
        data = self._load()

        self.assertEqual(
            data.close_prices_by_stock['600001'],
            {day: Decimal(10 + index) for index, day in enumerate(self.days)},
        )
        self.assertEqual(data.trading_days, self.days)
        self.assertEqual(data.business_date, self.business_date)
        self.assertEqual(data.stock_names_by_code['600001'], '测试股票')

    def test_a_row_outside_the_window_is_not_part_of_it(self):
        """窗口只认交易日，不认"库里的最新写入"。

        滑窗极值的分母是窗口内的交易日。窗口外（更早）的行若也进来，199 日极值
        会被一段不属于它的历史拉低，而产物本身看不出任何异常。
        """
        earlier = date(2026, 9, 2)
        self._store_day(earlier, close=Decimal(1))

        data = self._load()

        self.assertNotIn(earlier, data.trading_days)
        self.assertEqual(
            data.close_prices_by_stock['600001'],
            {day: Decimal(10 + index) for index, day in enumerate(self.days)},
        )

    def test_a_day_without_a_valid_trade_contributes_no_close(self):
        """停牌日的行还在（它有 pre_close，有 has_valid_trade=False），收盘价按缺失处理。"""
        halted = self.days[1]
        DailyPrice.objects.filter(trade_date=halted).update(has_valid_trade=False)

        data = self._load()

        self.assertIsNone(data.close_prices_by_stock['600001'][halted])

    def test_the_target_day_quotes_cover_only_the_business_date(self):
        data = self._load()

        self.assertEqual(set(data.target_day_quotes), {'600001'})
