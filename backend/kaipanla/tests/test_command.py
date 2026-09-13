from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from io import StringIO
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from core.models import DataVersion, TradingDay
from kaipanla.services.fetcher import KaipanlaSectorFundFlowFetchResult
from kaipanla.services.parser import KaipanlaSectorFundFlowRow


class KaipanlaSectorFundFlowCommandTests(TestCase):
    databases = {'default', 'kaipanla'}

    def setUp(self):
        self.snapshot_time = timezone.make_aware(datetime(2026, 9, 8, 10, 5))
        TradingDay.objects.bulk_create([
            TradingDay(trade_date=value)
            for value in (
                date(2026, 9, 8), date(2026, 9, 9), date(2026, 9, 10), date(2026, 9, 11),
            )
        ])
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
        )

    def patch_now(self, *parts):
        """固定命令看到的那一刻：槽位判定只取决于运行时刻。"""
        return patch(
            'django.utils.timezone.now',
            return_value=timezone.make_aware(datetime(*parts)),
        )

    def local(self, *parts):
        return timezone.make_aware(datetime(*parts))

    @patch('kaipanla.management.commands.fetch_kaipanla_sector_fund_flow.KaipanlaSectorFundFlowFetcher')
    def test_latest_complete_fetch_writes_then_publishes_a_version(self, fetcher_class):
        fetcher_class.return_value.fetch.return_value = self.complete_result

        output = StringIO()
        with self.patch_now(2026, 9, 8, 10, 5):
            call_command('fetch_kaipanla_sector_fund_flow', '--latest', stdout=output)

        from kaipanla.models import KaipanlaSectorFundFlowRun, KaipanlaSectorFundFlowSnapshot

        self.assertEqual(KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').count(), 1)
        self.assertEqual(
            KaipanlaSectorFundFlowRun.objects.using('kaipanla').get().status,
            KaipanlaSectorFundFlowRun.Status.COMPLETE,
        )
        version = DataVersion.objects.get(dataset_key='kaipanla_sector_fund_flow')
        self.assertEqual(version.status, DataVersion.Status.COMPLETE)
        self.assertIn('published 1', output.getvalue())

    @patch('kaipanla.management.commands.fetch_kaipanla_sector_fund_flow.KaipanlaSectorFundFlowFetcher')
    def test_trading_session_run_floors_onto_a_standard_slot(self, fetcher_class):
        """盘中 09:33 运行 → 落库 09:30，并且能被读路径按固定槽位读到。"""
        from kaipanla.models import KaipanlaSectorFundFlowSnapshot
        from kaipanla.services.intraday import query_intraday

        fetcher_class.return_value.fetch.return_value = self.complete_result

        with self.patch_now(2026, 9, 8, 9, 33):
            call_command('fetch_kaipanla_sector_fund_flow')

        snapshot = KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').get()
        self.assertEqual(timezone.localtime(snapshot.snapshot_time), self.local(2026, 9, 8, 9, 30))
        self.assertEqual(
            [item['code'] for item in query_intraday(date(2026, 9, 8), inflow_top=1, outflow_top=1)['series']],
            ['BK001'],
        )

    @patch('kaipanla.management.commands.fetch_kaipanla_sector_fund_flow.KaipanlaSectorFundFlowFetcher')
    def test_repeated_runs_inside_one_five_minute_slot_overwrite_the_same_snapshot(self, fetcher_class):
        from kaipanla.models import KaipanlaSectorFundFlowSnapshot

        fetcher_class.return_value.fetch.return_value = self.complete_result
        with self.patch_now(2026, 9, 8, 9, 31):
            call_command('fetch_kaipanla_sector_fund_flow')

        fetcher_class.return_value.fetch.return_value = replace(
            self.complete_result,
            rows=(replace(self.complete_result.rows[0], main_net_inflow=Decimal('900000000')),),
        )
        with self.patch_now(2026, 9, 8, 9, 34):
            call_command('fetch_kaipanla_sector_fund_flow')

        snapshots = KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla')
        self.assertEqual(snapshots.count(), 1)
        snapshot = snapshots.get()
        self.assertEqual(timezone.localtime(snapshot.snapshot_time), self.local(2026, 9, 8, 9, 30))
        self.assertEqual(snapshot.main_net_inflow, Decimal('900000000'))

    @patch('kaipanla.management.commands.fetch_kaipanla_sector_fund_flow.KaipanlaSectorFundFlowFetcher')
    def test_post_close_run_lands_on_the_close_slot(self, fetcher_class):
        """盘后执行（16:34）落在 15:00，因此会刷新而不是新增收盘快照。"""
        from kaipanla.models import KaipanlaSectorFundFlowSnapshot
        from kaipanla.services.intraday import query_intraday

        fetcher_class.return_value.fetch.return_value = self.complete_result

        with self.patch_now(2026, 9, 8, 16, 34):
            call_command('fetch_kaipanla_sector_fund_flow', '--latest')

        snapshot = KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').get()
        self.assertEqual(timezone.localtime(snapshot.snapshot_time), self.local(2026, 9, 8, 15, 0))
        self.assertEqual(snapshot.trade_date, date(2026, 9, 8))
        self.assertEqual(
            DataVersion.objects.get(dataset_key='kaipanla_sector_fund_flow').business_date,
            date(2026, 9, 8),
        )
        self.assertEqual(
            [item['code'] for item in query_intraday(date(2026, 9, 8), inflow_top=1, outflow_top=1)['series']],
            ['BK001'],
        )

    @patch('kaipanla.management.commands.fetch_kaipanla_sector_fund_flow.KaipanlaSectorFundFlowFetcher')
    def test_non_trading_day_run_overwrites_the_previous_trading_close(self, fetcher_class):
        """周六（2026-09-12）采集必须归到最近交易日 2026-09-11 的 15:00，不产生当天快照。"""
        from kaipanla.models import KaipanlaSectorFundFlowSnapshot

        fetcher_class.return_value.fetch.return_value = self.complete_result

        with self.patch_now(2026, 9, 12, 6, 41):
            call_command('fetch_kaipanla_sector_fund_flow', '--latest')

        snapshot = KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').get()
        self.assertEqual(timezone.localtime(snapshot.snapshot_time), self.local(2026, 9, 11, 15, 0))
        self.assertEqual(snapshot.trade_date, date(2026, 9, 11))
        self.assertEqual(
            DataVersion.objects.get(dataset_key='kaipanla_sector_fund_flow').business_date,
            date(2026, 9, 11),
        )
        self.assertFalse(
            KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla')
            .filter(trade_date=date(2026, 9, 12)).exists()
        )

    @patch('kaipanla.management.commands.fetch_kaipanla_sector_fund_flow.KaipanlaSectorFundFlowFetcher')
    def test_pre_open_run_lands_on_the_previous_trading_close(self, fetcher_class):
        """交易日开盘前采集到的仍是上一交易日的完整数据，不能伪造成当天收盘快照。"""
        from kaipanla.models import KaipanlaSectorFundFlowSnapshot

        fetcher_class.return_value.fetch.return_value = self.complete_result

        with self.patch_now(2026, 9, 9, 9, 20):
            call_command('fetch_kaipanla_sector_fund_flow', '--latest')

        snapshot = KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').get()
        self.assertEqual(timezone.localtime(snapshot.snapshot_time), self.local(2026, 9, 8, 15, 0))
        self.assertEqual(snapshot.trade_date, date(2026, 9, 8))

    @patch('kaipanla.management.commands.fetch_kaipanla_sector_fund_flow.default_file_cache')
    @patch('kaipanla.management.commands.fetch_kaipanla_sector_fund_flow.KaipanlaSectorFundFlowFetcher')
    def test_success_invalidates_only_the_kaipanla_cache_after_publication(self, fetcher_class, cache_factory):
        fetcher_class.return_value.fetch.return_value = self.complete_result
        cache = Mock()
        cache_factory.return_value = cache

        with self.patch_now(2026, 9, 8, 10, 5):
            call_command('fetch_kaipanla_sector_fund_flow', '--latest')

        cache.invalidate_module.assert_called_once_with('kaipanla')

    @patch('kaipanla.management.commands.fetch_kaipanla_sector_fund_flow.KaipanlaSectorFundFlowFetcher')
    def test_incomplete_fetch_fails_without_replacing_an_existing_snapshot(self, fetcher_class):
        from kaipanla.models import KaipanlaSectorFundFlowSnapshot

        KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').create(
            sector_code='OLD', sector_name='旧快照', trade_date=self.snapshot_time.date(),
            snapshot_time=self.snapshot_time, main_net_inflow=Decimal('1'), source_batch_id='old',
        )
        fetcher_class.return_value.fetch.return_value = KaipanlaSectorFundFlowFetchResult(
            rows=(), is_complete=False, expected_page_count=2, completed_page_count=1,
            failed_page_offsets=(80,), source_timestamp=int(self.snapshot_time.timestamp()),
            source_trade_date='2026-09-08', error_summary='A required page failed.',
        )

        with self.patch_now(2026, 9, 8, 10, 5):
            with self.assertRaises(CommandError):
                call_command('fetch_kaipanla_sector_fund_flow', '--latest')

        self.assertEqual(KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').count(), 1)
        self.assertEqual(KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').get().sector_code, 'OLD')
        self.assertFalse(DataVersion.objects.filter(dataset_key='kaipanla_sector_fund_flow').exists())

    @patch('kaipanla.management.commands.fetch_kaipanla_sector_fund_flow.KaipanlaSectorFundFlowFetcher')
    def test_dry_run_never_writes_snapshots_runs_or_versions(self, fetcher_class):
        fetcher_class.return_value.fetch.return_value = self.complete_result

        with self.patch_now(2026, 9, 8, 10, 5):
            call_command('fetch_kaipanla_sector_fund_flow', '--latest', '--dry-run')

        from kaipanla.models import KaipanlaSectorFundFlowRun, KaipanlaSectorFundFlowSnapshot

        self.assertFalse(KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').exists())
        self.assertFalse(KaipanlaSectorFundFlowRun.objects.using('kaipanla').exists())
        self.assertFalse(DataVersion.objects.filter(dataset_key='kaipanla_sector_fund_flow').exists())

    @patch('kaipanla.management.commands.fetch_kaipanla_sector_fund_flow.write_complete_snapshot')
    @patch('kaipanla.management.commands.fetch_kaipanla_sector_fund_flow.KaipanlaSectorFundFlowFetcher')
    def test_a_failed_write_marks_the_version_failed_instead_of_publishing_it(
        self, fetcher_class, write_complete_snapshot
    ):
        """写行与发布在同一处收口：写失败 ⇒ 版本是 failed，绝不留一个 complete 版本。

        否则读路径会拿不到 complete 版本而报 404/409，却同时又有一批**没有版本戳**的
        行躺在库里 —— 这正是靠 ``source_data_version`` 过滤要避免的状态。
        """
        fetcher_class.return_value.fetch.return_value = self.complete_result
        write_complete_snapshot.side_effect = RuntimeError('database is locked')

        with self.patch_now(2026, 9, 8, 10, 5):
            with self.assertRaises(CommandError):
                call_command('fetch_kaipanla_sector_fund_flow', '--latest')

        version = DataVersion.objects.get(dataset_key='kaipanla_sector_fund_flow')
        self.assertEqual(version.status, DataVersion.Status.FAILED)
        self.assertIn('database is locked', version.error_summary)
        self.assertIsNone(version.last_success_at)
        self.assertIsNotNone(version.finished_at)
        self.assertFalse(
            DataVersion.objects.filter(
                dataset_key='kaipanla_sector_fund_flow',
                status=DataVersion.Status.COMPLETE,
            ).exists()
        )

    @patch('kaipanla.management.commands.fetch_kaipanla_sector_fund_flow.write_complete_snapshot')
    @patch('kaipanla.management.commands.fetch_kaipanla_sector_fund_flow.KaipanlaSectorFundFlowFetcher')
    def test_a_run_after_a_failed_write_can_still_publish(
        self, fetcher_class, write_complete_snapshot
    ):
        """失败的版本不能把后续重试钉死：下一轮完整采集应正常发布。"""
        fetcher_class.return_value.fetch.return_value = self.complete_result
        write_complete_snapshot.side_effect = RuntimeError('database is locked')

        with self.patch_now(2026, 9, 8, 10, 5):
            with self.assertRaises(CommandError):
                call_command('fetch_kaipanla_sector_fund_flow', '--latest')

        write_complete_snapshot.side_effect = None
        write_complete_snapshot.return_value = Mock(record_count=1)

        with self.patch_now(2026, 9, 8, 10, 10):
            call_command('fetch_kaipanla_sector_fund_flow', '--latest')

        self.assertTrue(
            DataVersion.objects.filter(
                dataset_key='kaipanla_sector_fund_flow',
                status=DataVersion.Status.COMPLETE,
            ).exists()
        )

    def test_default_mode_requires_a_calendar_trading_day(self):
        from kaipanla.management.commands.fetch_kaipanla_sector_fund_flow import Command

        weekday_morning = timezone.make_aware(datetime(2026, 9, 14, 10, 0))

        self.assertFalse(Command._is_trading_session(weekday_morning))

        TradingDay.objects.create(trade_date=weekday_morning.date())

        self.assertTrue(Command._is_trading_session(weekday_morning))
        self.assertFalse(
            Command._is_trading_session(
                timezone.make_aware(datetime(2026, 9, 14, 12, 0))
            )
        )
