from io import StringIO
from unittest.mock import patch

from django.core.management import call_command, get_commands, load_command_class
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase

from core.management.base import BaseDataCommand
from core.services.locking import DatasetLocked
from core.services.sync_reference import ReferenceSyncResult


# 这份清单只是"有没有漏登记"的哨兵：锁定行为本身是遍历发现出来的，不靠它。
_DATA_COMMAND_NAMES = {
    'build_hundred_day',
    'build_sector_momentum',
    'build_stock_moves',
    'fetch_kaipanla_sector_fund_flow',
    'init_stock_daily_prices',
    'refresh_intraday_quotes',
    'sync_kaipanla_industry_snapshot',
    'sync_stock_daily_prices',
    'sync_stock_master',
    'sync_trading_calendar',
}

# 四个 --date 命令的必填值；其余参数都带默认值。填的是日期，命令的 type 也是
# date.fromisoformat，所以能通过解析。
_DATA_COMMAND_DATE = '2026-09-08'


def _discover_data_commands() -> set[str]:
    """从 Django 的命令注册表里发现所有 ``BaseDataCommand`` 子类。

    这里**必须**是发现而不是手写：原来的手写清单漏掉了新增的
    ``refresh_intraday_quotes``，于是"每个数据命令都要先抢数据集锁"这条不变量
    在它身上无人看守。发现式写法让"加了命令忘了登记"不可能再悄悄发生。
    """
    return {
        name
        for name, app_label in get_commands().items()
        if isinstance(load_command_class(app_label, name), BaseDataCommand)
    }


def _required_arguments(command_name: str) -> tuple[str, ...]:
    """补上命令的必填参数，让调用能走到"抢锁"那一步。

    参数从命令自己的 parser 里问出来，同样不手写：手写清单正是上一条不变量漏掉
    ``refresh_intraday_quotes`` 的同一种病。这里用了 argparse 的私有 ``_actions``
    —— 它没有公开的枚举接口，而漏一个必填参数的表现是"用例假成功"，不值得为
    避免私有属性冒这个险。
    """
    command = load_command_class(get_commands()[command_name], command_name)
    parser = command.create_parser('manage.py', command_name)
    arguments: list[str] = []
    for action in parser._actions:  # noqa: SLF001
        if action.required:
            arguments.extend(action.option_strings[:1])
            arguments.append(_DATA_COMMAND_DATE)
    return tuple(arguments)


class ManagementCommandContractTests(SimpleTestCase):
    def test_public_commands_reject_an_active_dataset_lock_before_calling_services(self):
        self.assertEqual(
            _discover_data_commands(),
            _DATA_COMMAND_NAMES,
            '数据命令清单变了：把新命令的 dataset_key 与锁语义核对后再更新这份哨兵。',
        )

        for command_name in sorted(_DATA_COMMAND_NAMES):
            with self.subTest(command=command_name):
                with (
                    patch(
                        'core.management.base.dataset_lock',
                        side_effect=DatasetLocked('core:test is already running.'),
                    ),
                    # 直接掐掉基类的方法：真跑起来会打上游，而且每个子类的服务入口
                    # 各不相同，逐个 patch 服务路径正是上一版会漏的原因。
                    patch.object(BaseDataCommand, 'run_data_sync') as run_data_sync,
                    self.assertRaises(CommandError) as caught,
                ):
                    call_command(command_name, *_required_arguments(command_name))

                run_data_sync.assert_not_called()
                self.assertIn('already running', str(caught.exception))

    def test_failure_logs_redact_sensitive_values_and_include_command_context(self):
        with (
            patch(
                'core.services.sync_reference.sync_stock_master',
                side_effect=RuntimeError(
                    'upstream rejected api_key=top-secret token=also-secret '
                    'device_id=device-secret'
                ),
            ),
            self.assertLogs('core.management', level='ERROR') as logs,
            self.assertRaises(CommandError),
        ):
            call_command('sync_stock_master', '--limit', '1')

        rendered = '\n'.join(logs.output)
        self.assertIn('module=core', rendered)
        self.assertIn('dataset=stock_master', rendered)
        self.assertIn('batch_id=', rendered)
        self.assertNotIn('top-secret', rendered)
        self.assertNotIn('also-secret', rendered)
        self.assertNotIn('device-secret', rendered)
        self.assertIn('[REDACTED]', rendered)

    def test_success_logs_duration_and_dry_run_context(self):
        with (
            patch(
                'core.services.sync_reference.sync_stock_master',
                return_value=ReferenceSyncResult('stock_master', 1, True),
            ),
            self.assertLogs('core.management', level='INFO') as logs,
        ):
            output = StringIO()
            call_command('sync_stock_master', '--limit', '1', '--dry-run', stdout=output)

        self.assertIn('dry-run', output.getvalue())
        rendered = '\n'.join(logs.output)
        self.assertIn('module=core', rendered)
        self.assertIn('dataset=stock_master', rendered)
        self.assertIn('dry_run=True', rendered)
        self.assertIn('duration_seconds=', rendered)
        self.assertIn('batch_id=', rendered)


class ManagementCommandRunStatusTests(TestCase):
    def test_successful_command_clears_the_prior_consecutive_failure_count(self):
        from core.integrations.hithink.contracts import HithinkTicker
        from core.models import ModuleRunStatus

        class SuccessfulHithinkClient:
            def list_a_share_tickers(self, *, limit, offset):
                if offset:
                    return ()
                return (HithinkTicker('000001.SZ', '000001', '平安银行', 'szse'),)

        ModuleRunStatus.objects.create(
            module_id='core',
            dataset_key='stock_master',
            status=ModuleRunStatus.Status.FAILED,
            completeness='failed',
            serving_stale=True,
            consecutive_failure_count=3,
            error_summary='old failure',
        )

        with patch(
            'core.services.sync_reference.HithinkClient',
            return_value=SuccessfulHithinkClient(),
        ):
            call_command('sync_stock_master', '--limit', '1')

        status = ModuleRunStatus.objects.get(module_id='core', dataset_key='stock_master')
        self.assertEqual(status.status, ModuleRunStatus.Status.SUCCESS)
        self.assertEqual(status.consecutive_failure_count, 0)
