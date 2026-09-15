from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from io import StringIO
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connections
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from kaipanla.services.fetcher import KaipanlaSectorFundFlowFetchResult
from kaipanla.services.parser import KaipanlaSectorFundFlowRow

COMMAND_MODULE = 'kaipanla.management.commands.fetch_kaipanla_sector_fund_flow'


class KaipanlaSectorFundFlowCommandTests(TestCase):
    databases = {'default', 'kaipanla'}

    def setUp(self):
        self.snapshot_time = timezone.make_aware(datetime(2026, 9, 8, 10, 5))
        self.complete_result = KaipanlaSectorFundFlowFetchResult(
            rows=(
                KaipanlaSectorFundFlowRow(
                    sector_code='BK001', sector_name='半导体', change_pct=Decimal('1.2'),
                    # 单位是元：读路径会 /1e8 再取一位小数，量级太小会被四舍五入成 0
                    # 从而被正负榜双双过滤掉。
                    main_net_inflow=Decimal('200000000'), main_buy=Decimal('300000000'),
                    main_sell=Decimal('100000000'),
                    large_order_net_inflow=Decimal('40000000'), volume_ratio=Decimal('1.1'),
                    turnover_amount=Decimal('100'), float_market_cap=Decimal('50'),
                    total_market_cap=Decimal('60'),
                ),
            ),
            is_complete=True,
            expected_page_count=1,
            completed_page_count=1,
            failed_page_offsets=(),
            source_timestamp=int(self.snapshot_time.timestamp()),
            source_trade_date='2026-09-08',
            upstream_record_count=1,
        )

    def patch_now(self, *parts):
        """固定命令看到的那一刻：槽位判定只取决于运行时刻。"""
        return patch(
            'django.utils.timezone.now',
            return_value=timezone.make_aware(datetime(*parts)),
        )

    def local(self, *parts):
        return timezone.make_aware(datetime(*parts))

    @staticmethod
    def snapshot_rows():
        from kaipanla.models import KaipanlaSectorFundFlowSnapshot

        return KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla')

    @patch(f'{COMMAND_MODULE}.KaipanlaSectorFundFlowFetcher')
    def test_latest_complete_fetch_writes_the_snapshot_and_nothing_else(self, fetcher_class):
        """写行即发布：一次成功采集只碰本模块这张表，跨库登记一笔都不写。"""
        fetcher_class.return_value.fetch.return_value = self.complete_result

        with CaptureQueriesContext(connections['default']) as default_queries:
            output = StringIO()
            with self.patch_now(2026, 9, 8, 10, 5):
                call_command('fetch_kaipanla_sector_fund_flow', '--latest', stdout=output)

        self.assertEqual(self.snapshot_rows().count(), 1)
        self.assertIn('published 1', output.getvalue())
        # 采集链路不再向默认库（DataVersion / ModuleRunStatus 的所在库）写任何东西。
        writes = [
            query['sql'] for query in default_queries.captured_queries
            if query['sql'].lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE'))
        ]
        self.assertEqual(writes, [])

    @patch(f'{COMMAND_MODULE}.KaipanlaSectorFundFlowFetcher')
    def test_trading_session_run_floors_onto_a_standard_slot(self, fetcher_class):
        """盘中 09:33 运行 → 落库 09:30，并且能被读路径按固定槽位读到。"""
        from kaipanla.services.intraday import query_intraday

        fetcher_class.return_value.fetch.return_value = self.complete_result

        with self.patch_now(2026, 9, 8, 9, 33):
            call_command('fetch_kaipanla_sector_fund_flow')

        snapshot = self.snapshot_rows().get()
        self.assertEqual(timezone.localtime(snapshot.snapshot_time), self.local(2026, 9, 8, 9, 30))
        self.assertEqual(
            [item['code'] for item in query_intraday(date(2026, 9, 8), inflow_top=1, outflow_top=1)['series']],
            ['BK001'],
        )

    @patch(f'{COMMAND_MODULE}.KaipanlaSectorFundFlowFetcher')
    def test_a_run_just_after_the_morning_close_collects_the_1130_slot(self, fetcher_class):
        """11:30 那一轮必须真的采集：cron 到点拉起进程，读到时钟时已越过整点。

        闸门若只把 11:30:00.000000 这一微秒算作盘中，`*/5 9-15` 的 11:30 那一轮
        每天都被 `skipped: outside_trading_session` 拒掉，库里就永远缺 11:30 槽（15:00
        同样越过右端点，只是另有 `--latest` 兜底才没暴露）。
        """
        from kaipanla.services.intraday import query_intraday

        fetcher_class.return_value.fetch.return_value = self.complete_result

        output = StringIO()
        with self.patch_now(2026, 9, 14, 11, 30, 1):
            call_command('fetch_kaipanla_sector_fund_flow', stdout=output)

        fetcher_class.assert_called_once()
        self.assertNotIn('skipped', output.getvalue())
        snapshot = self.snapshot_rows().get()
        self.assertEqual(
            timezone.localtime(snapshot.snapshot_time), self.local(2026, 9, 14, 11, 30)
        )
        self.assertEqual(snapshot.trade_date, date(2026, 9, 14))

        payload = query_intraday(date(2026, 9, 14), inflow_top=1, outflow_top=1)
        self.assertEqual(payload['time_points'][-1], '15:00')
        self.assertEqual(
            payload['time_points'][len(payload['series'][0]['data']) - 1], '11:30'
        )

    @patch(f'{COMMAND_MODULE}.KaipanlaSectorFundFlowFetcher')
    def test_repeated_runs_inside_one_five_minute_slot_overwrite_the_same_snapshot(self, fetcher_class):
        fetcher_class.return_value.fetch.return_value = self.complete_result
        with self.patch_now(2026, 9, 8, 9, 31):
            call_command('fetch_kaipanla_sector_fund_flow')

        fetcher_class.return_value.fetch.return_value = replace(
            self.complete_result,
            rows=(replace(self.complete_result.rows[0], main_net_inflow=Decimal('900000000')),),
        )
        with self.patch_now(2026, 9, 8, 9, 34):
            call_command('fetch_kaipanla_sector_fund_flow')

        snapshots = self.snapshot_rows()
        self.assertEqual(snapshots.count(), 1)
        snapshot = snapshots.get()
        self.assertEqual(timezone.localtime(snapshot.snapshot_time), self.local(2026, 9, 8, 9, 30))
        self.assertEqual(snapshot.main_net_inflow, Decimal('900000000'))

    @patch(f'{COMMAND_MODULE}.KaipanlaSectorFundFlowFetcher')
    def test_post_close_run_lands_on_the_close_slot(self, fetcher_class):
        """盘后执行（16:34）落在 15:00，因此会刷新而不是新增收盘快照。"""
        from kaipanla.services.intraday import query_intraday

        fetcher_class.return_value.fetch.return_value = self.complete_result

        with self.patch_now(2026, 9, 8, 16, 34):
            call_command('fetch_kaipanla_sector_fund_flow', '--latest')

        snapshot = self.snapshot_rows().get()
        self.assertEqual(timezone.localtime(snapshot.snapshot_time), self.local(2026, 9, 8, 15, 0))
        self.assertEqual(snapshot.trade_date, date(2026, 9, 8))
        self.assertEqual(
            [item['code'] for item in query_intraday(date(2026, 9, 8), inflow_top=1, outflow_top=1)['series']],
            ['BK001'],
        )

    @patch(f'{COMMAND_MODULE}.KaipanlaSectorFundFlowFetcher')
    def test_non_trading_day_run_overwrites_the_previous_trading_close(self, fetcher_class):
        """周六（2026-09-12）采集必须归到最近交易日 2026-09-11 的 15:00，不产生当天快照。"""
        fetcher_class.return_value.fetch.return_value = self.complete_result

        with self.patch_now(2026, 9, 12, 6, 41):
            call_command('fetch_kaipanla_sector_fund_flow', '--latest')

        snapshot = self.snapshot_rows().get()
        self.assertEqual(timezone.localtime(snapshot.snapshot_time), self.local(2026, 9, 11, 15, 0))
        self.assertEqual(snapshot.trade_date, date(2026, 9, 11))
        self.assertFalse(self.snapshot_rows().filter(trade_date=date(2026, 9, 12)).exists())

    @patch(f'{COMMAND_MODULE}.KaipanlaSectorFundFlowFetcher')
    def test_pre_open_run_lands_on_the_previous_trading_close(self, fetcher_class):
        """交易日开盘前采集到的仍是上一交易日的完整数据，不能伪造成当天收盘快照。"""
        fetcher_class.return_value.fetch.return_value = self.complete_result

        with self.patch_now(2026, 9, 9, 9, 20):
            call_command('fetch_kaipanla_sector_fund_flow', '--latest')

        snapshot = self.snapshot_rows().get()
        self.assertEqual(timezone.localtime(snapshot.snapshot_time), self.local(2026, 9, 8, 15, 0))
        self.assertEqual(snapshot.trade_date, date(2026, 9, 8))

    @patch(f'{COMMAND_MODULE}.default_file_cache')
    @patch(f'{COMMAND_MODULE}.KaipanlaSectorFundFlowFetcher')
    def test_success_invalidates_only_the_kaipanla_cache(self, fetcher_class, cache_factory):
        fetcher_class.return_value.fetch.return_value = self.complete_result
        cache = Mock()
        cache_factory.return_value = cache

        with self.patch_now(2026, 9, 8, 10, 5):
            call_command('fetch_kaipanla_sector_fund_flow', '--latest')

        cache.invalidate_module.assert_called_once_with('kaipanla')

    @patch(f'{COMMAND_MODULE}.KaipanlaSectorFundFlowFetcher')
    def test_incomplete_fetch_is_reported_in_the_log_and_writes_nothing(self, fetcher_class):
        """采集不全：一个字都不落库，账目全在那条 WARNING 日志里。

        `KaipanlaSectorFundFlowRun` 之前只回答三个问题——上游声称多少行、实际到了
        多少行、哪一页失败了。删表之后这三个数字必须仍然可查，否则"少了 40 个板块"
        就彻底查无实据；它们现在长在 `kaipanla_collection_incomplete` 这一行上。
        """
        self.snapshot_rows().create(
            sector_code='OLD', sector_name='旧快照', trade_date=self.snapshot_time.date(),
            snapshot_time=self.snapshot_time, main_net_inflow=Decimal('1'),
        )
        fetcher_class.return_value.fetch.return_value = KaipanlaSectorFundFlowFetchResult(
            rows=(), is_complete=False, expected_page_count=2, completed_page_count=1,
            failed_page_offsets=(80,), source_timestamp=int(self.snapshot_time.timestamp()),
            source_trade_date='2026-09-08', error_summary='A required page failed.',
            failure_kind='unavailable', upstream_record_count=104, invalid_row_count=3,
        )

        with self.patch_now(2026, 9, 8, 10, 5):
            with self.assertLogs(COMMAND_MODULE, level='WARNING') as captured:
                with self.assertRaises(CommandError):
                    call_command('fetch_kaipanla_sector_fund_flow', '--latest')

        # 旧快照原样保留，没有被半截数据覆盖，也没有新增任何行。
        self.assertEqual(self.snapshot_rows().count(), 1)
        self.assertEqual(self.snapshot_rows().get().sector_code, 'OLD')

        incomplete_lines = [
            line for line in captured.output if 'kaipanla_collection_incomplete' in line
        ]
        self.assertEqual(len(incomplete_lines), 1)
        line = incomplete_lines[0]
        self.assertIn('expected_record_count=104', line)
        self.assertIn('collected_record_count=0', line)
        self.assertIn('missing_record_count=104', line)
        self.assertIn('invalid_record_count=3', line)
        self.assertIn('page_progress=1/2', line)
        self.assertIn('failed_page_offsets=[80]', line)
        self.assertIn('failure_kind=unavailable', line)

    @patch(f'{COMMAND_MODULE}.KaipanlaSectorFundFlowFetcher')
    def test_dry_run_never_writes_snapshots(self, fetcher_class):
        fetcher_class.return_value.fetch.return_value = self.complete_result

        with self.patch_now(2026, 9, 8, 10, 5):
            call_command('fetch_kaipanla_sector_fund_flow', '--latest', '--dry-run')

        self.assertFalse(self.snapshot_rows().exists())

    @patch(f'{COMMAND_MODULE}.write_complete_snapshot')
    @patch(f'{COMMAND_MODULE}.KaipanlaSectorFundFlowFetcher')
    def test_a_failed_write_fails_the_command_without_leaving_a_half_slot(
        self, fetcher_class, write_complete_snapshot
    ):
        """写行即发布：写失败时既没有行，也没有"已发布"的残留状态需要收拾。

        没有登记表就没有 `DataVersion` 可以标 failed —— 也不需要：那个状态的
        全部意义是拦住读路径读一批尚未发布的版本，而现在写行即发布。
        """
        fetcher_class.return_value.fetch.return_value = self.complete_result
        write_complete_snapshot.side_effect = RuntimeError('database is locked')

        with self.patch_now(2026, 9, 8, 10, 5):
            with self.assertRaises(CommandError):
                call_command('fetch_kaipanla_sector_fund_flow', '--latest')

        self.assertEqual(self.snapshot_rows().count(), 0)

    @patch(f'{COMMAND_MODULE}.write_complete_snapshot')
    @patch(f'{COMMAND_MODULE}.KaipanlaSectorFundFlowFetcher')
    def test_a_run_after_a_failed_write_still_publishes(self, fetcher_class, write_complete_snapshot):
        """失败不写任何状态，所以也不可能把后续重试钉死。"""
        fetcher_class.return_value.fetch.return_value = self.complete_result
        write_complete_snapshot.side_effect = RuntimeError('database is locked')

        with self.patch_now(2026, 9, 8, 10, 5):
            with self.assertRaises(CommandError):
                call_command('fetch_kaipanla_sector_fund_flow', '--latest')

        write_complete_snapshot.side_effect = None
        write_complete_snapshot.return_value = 1

        output = StringIO()
        with self.patch_now(2026, 9, 8, 10, 10):
            call_command('fetch_kaipanla_sector_fund_flow', '--latest', stdout=output)

        self.assertIn('published 1', output.getvalue())

    @patch(f'{COMMAND_MODULE}.KaipanlaSectorFundFlowFetcher')
    def test_default_mode_skips_the_midday_break_without_touching_upstream(self, fetcher_class):
        """午休默认模式直接退出：不采集、不落库、不写失败日志，crontab 拿到干净的跳过。"""
        output = StringIO()
        with self.patch_now(2026, 9, 14, 12, 0):
            call_command('fetch_kaipanla_sector_fund_flow', stdout=output)

        fetcher_class.assert_not_called()
        self.assertIn('skipped', output.getvalue())
        self.assertEqual(self.snapshot_rows().count(), 0)

    @patch(f'{COMMAND_MODULE}.KaipanlaSectorFundFlowFetcher')
    def test_default_mode_skips_a_weekend_and_a_holiday(self, fetcher_class):
        """非交易日即使落在时段钟点内也必须跳过。"""
        for moment in ((2026, 9, 12, 10, 0), (2026, 10, 1, 10, 0)):  # 周六 / 国庆
            with self.subTest(moment=moment), self.patch_now(*moment):
                call_command('fetch_kaipanla_sector_fund_flow', stdout=StringIO())

        fetcher_class.assert_not_called()

    @patch(f'{COMMAND_MODULE}.KaipanlaSectorFundFlowFetcher')
    def test_latest_bypasses_the_session_gate_on_a_non_trading_day(self, fetcher_class):
        """--latest 是闸门的唯一旁路：非交易日也必须真的执行。"""
        fetcher_class.return_value.fetch.return_value = self.complete_result

        with self.patch_now(2026, 9, 12, 10, 0):  # 周六
            call_command('fetch_kaipanla_sector_fund_flow', '--latest')

        fetcher_class.assert_called_once()
        self.assertEqual(self.snapshot_rows().count(), 1)
