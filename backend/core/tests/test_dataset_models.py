from datetime import date
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase


class DailyPriceModelTests(TestCase):
    def setUp(self):
        from core.models import Stock

        self.stock = Stock.objects.create(
            thscode='000001.SZ',
            stock_code='000001',
            stock_name='平安银行',
            exchange=Stock.Exchange.SZSE,
        )

    def test_daily_price_is_unique_per_stock_and_trade_date(self):
        from core.models import DailyPrice

        values = {
            'stock': self.stock,
            'trade_date': date(2026, 9, 8),
            'pre_close': Decimal('10.00'),
            'open_price': Decimal('10.10'),
            'high_price': Decimal('10.30'),
            'low_price': Decimal('9.90'),
            'close_price': Decimal('10.20'),
            'change_percent': Decimal('2.00'),
            'volume': 1000,
            'turnover': Decimal('10200.00'),
            'has_valid_trade': True,
            'source_batch_id': 'batch-20260908',
        }
        DailyPrice.objects.create(**values)

        with self.assertRaises(IntegrityError), transaction.atomic():
            DailyPrice.objects.create(**values)

    def test_daily_price_keeps_the_batch_that_wrote_it(self):
        """``source_batch_id`` 是"哪一次同步写了这一行"，不是版本号，必须留着。

        它是运维回答"这一天是谁刷进来的"的唯一线索，所以整批 upsert 只更新业务
        字段、不动这一列。
        """
        from core.models import DailyPrice

        row = DailyPrice.objects.create(
            stock=self.stock,
            trade_date=date(2026, 9, 8),
            has_valid_trade=True,
            source_batch_id='batch-20260908',
        )

        row.refresh_from_db()
        self.assertEqual(row.source_batch_id, 'batch-20260908')
