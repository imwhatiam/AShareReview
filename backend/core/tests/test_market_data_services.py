from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.test import TestCase


SHANGHAI = ZoneInfo('Asia/Shanghai')


class MarketCalendarBoundaryTests(TestCase):
    def test_before_market_close_uses_previous_trading_day(self):
        from core.services.calendar import latest_eligible_trading_day

        actual = latest_eligible_trading_day(
            datetime(2026, 9, 7, 14, 59, 59, tzinfo=SHANGHAI)
        )

        self.assertEqual(actual, date(2026, 9, 4))

    def test_at_market_close_allows_current_trading_day(self):
        from core.services.calendar import latest_eligible_trading_day

        actual = latest_eligible_trading_day(
            datetime(2026, 9, 7, 15, 0, 0, tzinfo=SHANGHAI)
        )

        self.assertEqual(actual, date(2026, 9, 7))

    def test_a_non_trading_day_falls_back_to_the_previous_trading_day(self):
        from core.services.calendar import latest_eligible_trading_day

        weekend = latest_eligible_trading_day(
            datetime(2026, 9, 6, 11, 0, tzinfo=SHANGHAI)
        )
        holiday = latest_eligible_trading_day(
            datetime(2026, 10, 1, 11, 0, tzinfo=SHANGHAI)
        )

        self.assertEqual(weekend, date(2026, 9, 4))
        self.assertEqual(holiday, date(2026, 9, 30))


class LatestStoredPriceDateTests(TestCase):
    """默认入口锚点只有一个来源：库里最新的一天公共日行情。

    以前它查的是 ``DataVersion`` 的 complete 行；版本表删掉之后，"这一天有完整
    数据"与"这一天有行"是同一件事，所以这里用真实行来驱动。
    """

    def setUp(self):
        from core.models import Stock

        self.stock = Stock.objects.create(
            thscode='000001.SZ',
            stock_code='000001',
            stock_name='平安银行',
            exchange=Stock.Exchange.SZSE,
        )
        self._store_prices(date(2026, 9, 4))

    def _store_prices(self, trade_date):
        from core.models import DailyPrice

        DailyPrice.objects.create(
            stock=self.stock,
            trade_date=trade_date,
            close_price=Decimal('10.00'),
            has_valid_trade=True,
            source_batch_id=f'batch-{trade_date:%Y%m%d}',
        )

    def test_close_time_still_reports_the_newest_day_that_has_rows(self):
        from core.services.market_data import latest_complete_stock_price_date

        actual = latest_complete_stock_price_date(
            datetime(2026, 9, 7, 15, 0, tzinfo=SHANGHAI)
        )

        self.assertEqual(actual, date(2026, 9, 4))

    def test_stored_intraday_rows_promote_the_default_entry_to_today(self):
        """盘中刷新给当天写进真实行后，默认入口必须跟当天，而不是停在昨天。"""
        from core.services.market_data import latest_complete_stock_price_date

        self._store_prices(date(2026, 9, 7))

        actual = latest_complete_stock_price_date(
            datetime(2026, 9, 7, 14, 0, tzinfo=SHANGHAI)
        )

        self.assertEqual(actual, date(2026, 9, 7))

    def test_without_today_rows_the_default_entry_stays_on_the_previous_day(self):
        from core.services.market_data import latest_complete_stock_price_date

        actual = latest_complete_stock_price_date(
            datetime(2026, 9, 7, 14, 0, tzinfo=SHANGHAI)
        )

        self.assertEqual(actual, date(2026, 9, 4))

    def test_no_stored_rows_at_all_means_no_default_entry(self):
        from core.models import DailyPrice
        from core.services.market_data import latest_complete_stock_price_date

        DailyPrice.objects.all().delete()

        self.assertIsNone(
            latest_complete_stock_price_date(
                datetime(2026, 9, 7, 15, 0, tzinfo=SHANGHAI)
            )
        )


class CompleteMarketSnapshotTests(TestCase):
    def test_snapshot_uses_plain_contracts_and_every_industry(self):
        from core.models import DailyPrice, IndustrySnapshot, Stock
        from core.services.market_data import get_complete_market_snapshot

        szse_stock = Stock.objects.create(
            thscode='000001.SZ',
            stock_code='000001',
            stock_name='平安银行',
            exchange=Stock.Exchange.SZSE,
        )
        bse_stock = Stock.objects.create(
            thscode='430047.BJ',
            stock_code='430047',
            stock_name='诺思兰德',
            exchange=Stock.Exchange.BSE,
        )
        for stock, price in ((szse_stock, '10.00'), (bse_stock, '20.00')):
            DailyPrice.objects.create(
                stock=stock,
                trade_date=date(2026, 9, 4),
                close_price=Decimal(price),
                has_valid_trade=True,
                source_batch_id='batch-20260904',
            )
        IndustrySnapshot.objects.create(
            industry_code='801660',
            industry_name='通信',
            stock_codes=['000001', '430047'],
        )
        IndustrySnapshot.objects.create(
            industry_code='801206',
            industry_name='光模块',
            stock_codes=['000001'],
        )

        snapshot = get_complete_market_snapshot(date(2026, 9, 4))

        self.assertEqual(snapshot.business_date, date(2026, 9, 4))
        self.assertEqual(
            [(price.stock_code, price.exchange) for price in snapshot.prices],
            [('000001', 'szse'), ('430047', 'bse')],
        )
        self.assertEqual(
            [(industry.code, industry.name) for industry in snapshot.industries],
            [('801206', '光模块'), ('801660', '通信')],
        )
        self.assertFalse(hasattr(snapshot.prices[0], '_meta'))

    def test_a_day_without_rows_is_unavailable_rather_than_empty(self):
        """没有行要让调用方看到"不可用"，不能返回一个空快照让分析算出全零。"""
        from core.services.market_data import (
            CompleteMarketDataUnavailable,
            get_complete_market_snapshot,
        )

        with self.assertRaises(CompleteMarketDataUnavailable):
            get_complete_market_snapshot(date(2026, 9, 4))
