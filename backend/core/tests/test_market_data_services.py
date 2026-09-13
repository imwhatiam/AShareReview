from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.test import TestCase


SHANGHAI = ZoneInfo('Asia/Shanghai')


class MarketDataServiceTests(TestCase):
    def setUp(self):
        from core.models import DataVersion, TradingDay

        for trade_date in (date(2026, 9, 4), date(2026, 9, 7)):
            TradingDay.objects.create(trade_date=trade_date)

        DataVersion.objects.create(
            dataset_key='stock_daily_prices',
            version='prices-20260904-v1',
            business_date=date(2026, 9, 4),
            status=DataVersion.Status.COMPLETE,
            expected_record_count=1,
            actual_record_count=1,
        )
        DataVersion.objects.create(
            dataset_key='stock_daily_prices',
            version='prices-20260907-v1',
            business_date=date(2026, 9, 7),
            status=DataVersion.Status.PARTIAL,
            expected_record_count=1,
            actual_record_count=0,
            missing_record_count=1,
        )

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

    def test_weekend_and_calendar_holiday_fall_back_to_latest_calendar_day(self):
        from core.services.calendar import latest_eligible_trading_day

        weekend = latest_eligible_trading_day(
            datetime(2026, 9, 6, 11, 0, tzinfo=SHANGHAI)
        )
        calendar_holiday = latest_eligible_trading_day(
            datetime(2026, 9, 8, 11, 0, tzinfo=SHANGHAI)
        )

        self.assertEqual(weekend, date(2026, 9, 4))
        self.assertEqual(calendar_holiday, date(2026, 9, 7))

    def test_latest_complete_date_skips_partial_current_version(self):
        from core.services.market_data import latest_complete_stock_price_date

        actual = latest_complete_stock_price_date(
            datetime(2026, 9, 7, 15, 0, tzinfo=SHANGHAI)
        )

        self.assertEqual(actual, date(2026, 9, 4))

    def test_intraday_version_promotes_the_default_entry_to_today(self):
        """盘中刷新发布当天的完整版本后，默认入口必须跟当天，而不是停在昨天。"""
        from core.models import DataVersion
        from core.services.market_data import latest_complete_stock_price_date

        DataVersion.objects.create(
            dataset_key='stock_daily_prices',
            version='prices-20260907-intraday',
            business_date=date(2026, 9, 7),
            status=DataVersion.Status.COMPLETE,
            expected_record_count=1,
            actual_record_count=1,
        )

        actual = latest_complete_stock_price_date(
            datetime(2026, 9, 7, 14, 0, tzinfo=SHANGHAI)
        )

        self.assertEqual(actual, date(2026, 9, 7))

    def test_without_an_intraday_version_the_default_entry_stays_yesterday(self):
        """当天还没有完整版本时（例如 09:30 前），行为与收盘前一致。"""
        from core.services.market_data import latest_complete_stock_price_date

        actual = latest_complete_stock_price_date(
            datetime(2026, 9, 7, 14, 0, tzinfo=SHANGHAI)
        )

        self.assertEqual(actual, date(2026, 9, 4))

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
                source_data_version='prices-20260904-v1',
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

        self.assertEqual(snapshot.data_version.version, 'prices-20260904-v1')
        self.assertEqual(
            [(price.stock_code, price.exchange) for price in snapshot.prices],
            [('000001', 'szse'), ('430047', 'bse')],
        )
        self.assertEqual(
            [(industry.code, industry.name) for industry in snapshot.industries],
            [('801206', '光模块'), ('801660', '通信')],
        )
        self.assertFalse(hasattr(snapshot.prices[0], '_meta'))
