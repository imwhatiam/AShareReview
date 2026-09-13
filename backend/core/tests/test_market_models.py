from datetime import date

from django.db import IntegrityError, transaction
from django.test import TestCase


class MarketReferenceModelTests(TestCase):
    def test_industry_snapshot_has_only_three_business_fields(self):
        from core.models import IndustrySnapshot

        fields = {
            field.name
            for field in IndustrySnapshot._meta.fields
            if field.name != 'id'
        }

        self.assertEqual(
            fields,
            {'industry_code', 'industry_name', 'stock_codes'},
        )

    def test_same_stock_can_belong_to_multiple_industries(self):
        from core.models import IndustrySnapshot

        IndustrySnapshot.objects.create(
            industry_code='801660',
            industry_name='通信',
            stock_codes=['000801', '300308'],
        )
        IndustrySnapshot.objects.create(
            industry_code='801080',
            industry_name='电子',
            stock_codes=['000801'],
        )

        self.assertEqual(IndustrySnapshot.objects.count(), 2)

    def test_stock_and_trading_day_have_their_natural_unique_keys(self):
        from core.models import Stock, TradingDay

        Stock.objects.create(
            thscode='000001.SZ',
            stock_code='000001',
            stock_name='平安银行',
            exchange=Stock.Exchange.SZSE,
        )
        TradingDay.objects.create(trade_date=date(2026, 9, 8))

        with self.assertRaises(IntegrityError), transaction.atomic():
            Stock.objects.create(
                thscode='000001.SZ',
                stock_code='000001',
                stock_name='重复',
                exchange=Stock.Exchange.SZSE,
            )
