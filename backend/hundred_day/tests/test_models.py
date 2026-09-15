from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from backend.db_router import AppDatabaseRouter
from hundred_day.models import (
    HundredDayBreadth,
    HundredDayIndustrySummary,
    HundredDayStockFlag,
)


class HundredDayModelTests(TestCase):
    databases = {'default', 'hundred_day'}

    def _breadth(self, trade_date=date(2026, 9, 8), **overrides):
        fields = {
            'business_date': date(2026, 9, 8),
            'trade_date': trade_date,
            'valid_stock_count': 100,
            'new_high_count': 12,
            'new_low_count': 8,
            'published_at': timezone.now(),
        }
        fields.update(overrides)
        return HundredDayBreadth.objects.create(**fields)

    def test_breadth_keeps_business_date_trade_date_and_market_level_counts(self):
        point = self._breadth()

        self.assertEqual(point.business_date, date(2026, 9, 8))
        self.assertEqual(point.trade_date, date(2026, 9, 8))
        self.assertEqual(point.valid_stock_count, 100)
        self.assertEqual(point.new_high_count, 12)
        self.assertEqual(point.new_low_count, 8)

    def test_one_business_date_holds_the_whole_trend(self):
        """趋势点与当日结果是同一张表：一个业务日期下有很多个交易日。

        合并前它们是两张表（``HundredDayResult`` + ``HundredDayTrend``），却是同一个
        粒度。现在同一次发布的市场宽度点全在这里，业务日期那一行就是"当日"。
        """
        for offset in range(3):
            self._breadth(trade_date=date(2026, 9, 4 + offset))

        stored = HundredDayBreadth.objects.filter(business_date=date(2026, 9, 8))
        self.assertEqual(stored.count(), 3)
        self.assertEqual(
            [point.trade_date for point in stored],  # Meta.ordering = ['trade_date']
            [date(2026, 9, 4), date(2026, 9, 5), date(2026, 9, 6)],
        )

    def test_the_same_trade_date_cannot_be_stored_twice_for_one_business_date(self):
        """(业务日期, 交易日) 唯一：重跑是覆盖这一点，不是追加第二个版本。"""
        self._breadth()

        with self.assertRaises(IntegrityError), transaction.atomic():
            self._breadth(valid_stock_count=999)

    def test_published_at_is_stamped_by_the_writer_not_by_the_model(self):
        """发布时间由写入方显式给值 —— 重跑必须能把它往前推。

        若它是 ``auto_now_add``，重跑写出来的行会保留第一次的时刻，文件缓存就会在
        TTL 内继续发上一版报文。这条把"可以显式写"钉死。
        """
        written_at = timezone.now() - timedelta(days=30)
        point = self._breadth(published_at=written_at)

        self.assertEqual(point.published_at, written_at)

    def test_stock_flag_is_unique_per_business_date_and_keeps_industries(self):
        flag = HundredDayStockFlag.objects.create(
            business_date=date(2026, 9, 8),
            stock_code='600000',
            stock_name='浦发银行',
            industries=[{'code': 'I001', 'name': '银行'}],
            is_new_high=True,
            is_new_low=False,
        )

        self.assertTrue(flag.is_new_high)
        self.assertEqual(flag.industries, [{'code': 'I001', 'name': '银行'}])
        with self.assertRaises(IntegrityError), transaction.atomic():
            HundredDayStockFlag.objects.create(
                business_date=date(2026, 9, 8),
                stock_code='600000',
                stock_name='重复股票',
            )

    def test_industry_summary_keeps_only_industry_level_facts(self):
        """行业级只留 ``stock_count``；新高/新低数量与名单是读时从个股标志算的。"""
        summary = HundredDayIndustrySummary.objects.create(
            business_date=date(2026, 9, 8),
            industry_code='I001',
            industry_name='银行',
            stock_count=3,
        )

        self.assertEqual(summary.stock_count, 3)
        for removed in ('new_high_count', 'new_low_count', 'new_high_stocks', 'new_low_stocks'):
            self.assertFalse(
                hasattr(summary, removed), f'{removed} 不该再是行业汇总的字段'
            )

    def test_stock_flag_keeps_the_target_day_quote(self):
        """行业明细要展示的涨幅与成交额随标志一起落库，读时不必再查公共行情。"""
        flag = HundredDayStockFlag.objects.create(
            business_date=date(2026, 9, 8),
            stock_code='600000',
            stock_name='浦发银行',
            industries=[{'code': 'I001', 'name': '银行'}],
            is_new_high=True,
            change_percent=Decimal('3.210000'),
            turnover=Decimal('98765432.1000'),
        )

        self.assertEqual(flag.change_percent, Decimal('3.210000'))
        self.assertEqual(flag.turnover, Decimal('98765432.1000'))

    def test_the_derived_ratios_are_no_longer_columns(self):
        """比值由除法得出，不再占一列 —— 旧 HundredDayTrend 的 two ratio 字段已删。"""
        for removed in ('new_high_ratio', 'new_low_ratio'):
            self.assertFalse(
                hasattr(HundredDayBreadth, removed), f'{removed} 不该再是市场宽度的字段'
            )

    def test_invalid_flag_is_rejected_by_model_validation(self):
        flag = HundredDayStockFlag(
            business_date=date(2026, 9, 8),
            stock_code='600000',
            stock_name='浦发银行',
            is_new_high=False,
            is_new_low=False,
        )

        with self.assertRaises(ValidationError):
            flag.full_clean()

    def test_models_route_to_own_database_without_cross_database_foreign_keys(self):
        router = AppDatabaseRouter()
        models = (HundredDayBreadth, HundredDayStockFlag, HundredDayIndustrySummary)
        for model in models:
            self.assertEqual(router.db_for_read(model), 'hundred_day')
            self.assertEqual(router.db_for_write(model), 'hundred_day')
            for field in model._meta.get_fields():
                # 跨库外键在分库配置下永远不可能成立，所以三张表之间一个外键都没有：
                # 归属由 business_date 这个普通列表达，读路径按它过滤。
                self.assertFalse(
                    getattr(field, 'many_to_one', False) or getattr(field, 'one_to_one', False),
                    f'{model.__name__}.{field.name} 不该是关联字段',
                )
