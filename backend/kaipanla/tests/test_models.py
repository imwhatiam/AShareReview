from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
import re

from django.apps import apps
from django.db import IntegrityError, router, transaction
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from kaipanla.models import KaipanlaSectorFundFlowSnapshot


class KaipanlaModelTests(TestCase):
    databases = {'default', 'kaipanla'}

    def test_snapshot_keeps_upstream_amounts_and_is_unique_per_sector_and_time(self):
        snapshot_time = timezone.make_aware(datetime(2026, 9, 8, 10, 5))
        snapshot = KaipanlaSectorFundFlowSnapshot.objects.create(
            sector_code='BK001',
            sector_name='半导体',
            trade_date=date(2026, 9, 8),
            snapshot_time=snapshot_time,
            change_pct=Decimal('1.234'),
            main_net_inflow=Decimal('1200000.50'),
            main_buy=Decimal('2100000.00'),
            main_sell=Decimal('899999.50'),
            large_order_net_inflow=Decimal('500000.25'),
            volume_ratio=Decimal('2.100'),
            turnover_amount=Decimal('9000000.00'),
            float_market_cap=Decimal('100000000.00'),
            total_market_cap=Decimal('150000000.00'),
        )

        self.assertEqual(snapshot.snapshot_time, snapshot_time)
        self.assertEqual(snapshot.main_net_inflow, Decimal('1200000.50'))
        self.assertEqual(snapshot.turnover_amount, Decimal('9000000.00'))

        with self.assertRaises(IntegrityError), transaction.atomic():
            KaipanlaSectorFundFlowSnapshot.objects.create(
                sector_code='BK001',
                sector_name='重复板块',
                trade_date=date(2026, 9, 8),
                snapshot_time=snapshot_time,
                main_net_inflow=Decimal('1.00'),
            )

    def test_kaipanla_models_route_to_their_own_database(self):
        self.assertEqual(router.db_for_read(KaipanlaSectorFundFlowSnapshot), 'kaipanla')
        self.assertEqual(router.db_for_write(KaipanlaSectorFundFlowSnapshot), 'kaipanla')

    def test_the_snapshot_has_no_cross_database_foreign_keys(self):
        foreign_keys = [
            field
            for field in KaipanlaSectorFundFlowSnapshot._meta.get_fields()
            if getattr(field, 'many_to_one', False) or getattr(field, 'one_to_one', False)
        ]
        self.assertEqual(foreign_keys, [])


class KaipanlaModuleIsolationTests(SimpleTestCase):
    """The module owns one database and answers from it alone.

    These guards are the executable form of that boundary: they fail the moment
    someone re-introduces a second table or reaches into the core database, which
    is exactly the kind of coupling this module just had removed. A deliberate
    change of the boundary should have to delete a test that says why.
    """

    # core 的模型层是 default 库的入口。资金流的行写进自己那个库就是"已发布"，
    # 既不需要版本账本，也不需要运行态看板 —— 两张表都已删除。
    FORBIDDEN_CORE_MODULES = ('core.models',)

    def test_the_module_owns_exactly_one_table(self):
        model_names = sorted(
            model.__name__ for model in apps.get_app_config('kaipanla').get_models()
        )

        self.assertEqual(model_names, ['KaipanlaSectorFundFlowSnapshot'])

    def test_no_source_file_imports_the_core_database(self):
        import kaipanla

        package = Path(kaipanla.__file__).parent
        offenders = []
        for path in sorted(package.rglob('*.py')):
            # 迁移是历史脚本（0002 就是从 core.DataVersion 回填那两列的），
            # 它们是"当时做过的动作"的记录，不是当前代码的依赖。
            if {'migrations', 'tests'} & set(path.parts):
                continue
            source = path.read_text(encoding='utf-8')
            for module in self.FORBIDDEN_CORE_MODULES:
                if re.search(
                    rf'^\s*(?:from|import)\s+{re.escape(module)}\b', source, re.MULTILINE
                ):
                    offenders.append(f'{path.relative_to(package)} -> {module}')

        self.assertEqual(
            offenders,
            [],
            'kaipanla 只应读写自己的数据库；这些文件又去碰了 core 的库：'
            + ', '.join(offenders),
        )
