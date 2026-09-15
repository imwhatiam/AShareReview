from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, router, transaction
from django.test import TestCase
from django.utils import timezone

from stock_moves.models import StockMoveItem


class StockMoveModelTests(TestCase):
    databases = {'default', 'stock_moves'}

    def _item(self, **overrides):
        values = {
            'business_date': date(2026, 9, 8),
            'group': StockMoveItem.Group.SSE_RISE,
            'rank': 1,
            'stock_code': '600000',
            'stock_name': '浦发银行',
            'industries': [{'code': 'I001', 'name': '银行'}],
            'change_percent': Decimal('8.000000'),
            'turnover': Decimal('800000000.0000'),
            'published_at': timezone.now(),
        }
        values.update(overrides)
        return StockMoveItem(**values)

    def test_one_table_carries_both_the_day_and_its_stocks(self):
        """单表：业务日期与发布时间就在明细行上，没有单独的结果表。"""
        item = self._item()
        item.save(using='stock_moves')

        self.assertEqual(item.business_date, date(2026, 9, 8))
        self.assertEqual(item.group, StockMoveItem.Group.SSE_RISE)
        self.assertEqual(item.rank, 1)
        self.assertEqual(item.industries, [{'code': 'I001', 'name': '银行'}])
        self.assertIsNotNone(item.published_at)
        self.assertFalse(hasattr(item, 'result_id'))

    def test_a_group_rank_is_unique_per_business_date_not_globally(self):
        """唯一性按天算：不同交易日可以有同样的（组, 名次）。"""
        self._item().save(using='stock_moves')
        self._item(business_date=date(2026, 9, 9), stock_code='600001').save(
            using='stock_moves'
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            self._item(stock_code='600002').save(using='stock_moves')

    def test_a_stock_appears_at_most_once_per_business_date(self):
        """一只股票在同一天只进一个组，所以同一天内代码唯一。"""
        self._item().save(using='stock_moves')

        with self.assertRaises(IntegrityError), transaction.atomic():
            self._item(group=StockMoveItem.Group.SSE_FALL, rank=1).save(
                using='stock_moves'
            )

    def test_group_choices_cover_every_market_and_direction_pair(self):
        self.assertEqual(
            list(StockMoveItem.Group.values),
            [
                'sse_rise', 'sse_fall',
                'szse_rise', 'szse_fall',
                'bse_rise', 'bse_fall',
            ],
        )

    def test_item_rejects_unknown_group(self):
        item = self._item(group='other')

        with self.assertRaises(ValidationError):
            item.full_clean()

    def test_models_route_to_stock_moves_database_and_have_no_cross_database_foreign_keys(self):
        self.assertEqual(router.db_for_read(StockMoveItem), 'stock_moves')
        self.assertEqual(router.db_for_write(StockMoveItem), 'stock_moves')

        foreign_keys = [
            field for field in StockMoveItem._meta.get_fields()
            if (getattr(field, 'many_to_one', False) or getattr(field, 'one_to_one', False))
        ]
        for field in foreign_keys:
            self.assertEqual(field.related_model._meta.app_label, 'stock_moves')
